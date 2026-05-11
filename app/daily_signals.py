import logging
import httpx
from app.database import supabase
from app.config import TELEGRAM_BOT_TOKEN
from app.signal_engine import get_latest_stocks, get_all_history_bulk, score_stock, generate_targets, clean_price, get_recently_signalled_tickers
from app.broadcaster import get_active_paid_users, _send
from datetime import datetime, UTC, date

logger = logging.getLogger(__name__)

def run_daily_signal_engine() -> list:
    logger.info("Running daily signal engine...")
    stocks = get_latest_stocks()
    if not stocks:
        return []

    history_map = get_all_history_bulk(days=10)
    recently_signalled = get_recently_signalled_tickers(weeks=1)

    scored = []
    for stock in stocks:
        ticker = stock["ticker"]
        if ticker in recently_signalled:
            continue
        history = history_map.get(ticker, [])
        score = score_stock(stock, history)
        if score > 0:
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