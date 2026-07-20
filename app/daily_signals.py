import logging
import httpx
from app.database import supabase
from app.config import TELEGRAM_BOT_TOKEN
from app.signal_engine import get_latest_stocks, get_all_history_bulk, score_stock, generate_targets, clean_price, get_recently_signalled_tickers, is_tradeable_equity, check_market_breadth
from app.broadcaster import get_active_paid_users, _send
from datetime import datetime, UTC, date

logger = logging.getLogger(__name__)

def run_daily_signal_engine() -> list:
    logger.info("Running daily signal engine...")
    stocks = get_latest_stocks()
    if not stocks:
        return []

    # market breadth check
    from app.signal_engine import check_market_breadth
    breadth = check_market_breadth(stocks)
    logger.info(f"Daily signal breadth: {breadth:.1%}")
    if breadth < 0.40:
        logger.warning(f"Market breadth too low ({breadth:.1%}) — skipping daily signals")
        return []

    history_map = get_all_history_bulk(days=10)
    recently_signalled = get_recently_signalled_tickers(weeks=1)

    scored = []
    for stock in stocks:
        ticker = stock["ticker"]
        company = stock.get("company", "")

        if not is_tradeable_equity(ticker, company):
            continue
        if ticker in recently_signalled:
            continue

        history = history_map.get(ticker, [])
        score = score_stock(stock, history)

        # minimum 35 points for daily signals — slightly lower than weekly
        if score >= 35:
            scored.append((score, stock, history))

    scored.sort(key=lambda x: x[0], reverse=True)
    top3 = scored[:3]

    signals = []
    for score, stock, history in top3:
        price = clean_price(stock["price"])
        targets = generate_targets(price)
        signals.append({"ticker": stock["ticker"], "score": score, **targets})
        logger.info(f"Daily signal: {stock['ticker']} | Score: {score:.1f} | Entry: ₦{price}")

    return signals

async def broadcast_daily_signals():
    signals = run_daily_signal_engine()
    if not signals:
        return

    pro_users = get_active_paid_users(["pro"])
    if not pro_users:
        return

    # save signals to database so outcomes get tracked
    from datetime import datetime, UTC
    week_start = date.today().isoformat()

    for s in signals:
        # save to signals table
        supabase.table("signals").insert({
            "ticker": s["ticker"],
            "market": "NGX",
            "status": "active",
            "entry_price": s["entry_price"],
            "tp1": s["tp1"],
            "tp2": s["tp2"],
            "stop_loss": s["stop_loss"],
            "created_at": datetime.now(UTC).isoformat()
        }).execute()

        # save to signal_history so check_outcomes tracks it
        supabase.table("signal_history").upsert({
            "ticker": s["ticker"],
            "week_start": week_start,
            "entry_price": s["entry_price"],
            "tp1": s["tp1"],
            "tp2": s["tp2"],
            "stop_loss": s["stop_loss"]
        }, on_conflict="ticker,week_start").execute()

    msg = f"📊 Daily Pro Signals — {date.today().strftime('%A %d %B')}\n\n"
    for i, s in enumerate(signals, 1):
        msg += (
            f"{i}. {s['ticker']}\n"
            f"Entry: ₦{s['entry_price']}\n"
            f"TP1: ₦{s['tp1']} (+6%)\n"
            f"TP2: ₦{s['tp2']} (+12%)\n"
            f"Stop Loss: ₦{s['stop_loss']}\n\n"
        )
    msg += "⚠️ Daily signals carry higher risk. Use smaller position sizes."

    sent = 0
    for user in pro_users:
        await _send(user["telegram_id"], msg)
        sent += 1

    logger.info(f"Daily signals sent to {sent} Pro users")