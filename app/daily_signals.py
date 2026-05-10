import logging
from app.database import supabase
from app.signal_engine import get_latest_stocks, get_all_history_bulk, score_stock, generate_targets, clean_price, get_recently_signalled_tickers
from datetime import datetime, UTC, date

logger = logging.getLogger(__name__)

def run_daily_signal_engine() -> list:
    logger.info("Running daily signal engine for Pro users...")

    stocks = get_latest_stocks()
    if not stocks:
        logger.warning("No stocks for daily signals")
        return []

    history_map = get_all_history_bulk(days=10)
    
    # for daily signals we still avoid recently signalled but with shorter window
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

    if not top3:
        return []

    signals = []
    for score, stock, history in top3:
        price = clean_price(stock["price"])
        targets = generate_targets(price)
        signals.append({
            "ticker": stock["ticker"],
            "score": score,
            **targets
        })
        logger.info(f"Daily signal: {stock['ticker']} | Score: {score:.1f} | Entry: ₦{price}")

    return signals

async def broadcast_daily_signals(bot):
    signals = run_daily_signal_engine()
    if not signals:
        logger.info("No daily signals to broadcast")
        return

    result = supabase.table("users")\
        .select("telegram_id, tier, expires_at")\
        .eq("tier", "pro")\
        .execute()

    pro_users = []
    for user in (result.data or []):
        expires_at = user.get("expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp > datetime.now(UTC):
                    pro_users.append(user)
            except:
                continue

    if not pro_users:
        logger.info("No Pro users for daily signals")
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
    msg += "⚠️ Daily signals carry higher risk than weekly signals. Use smaller position sizes."

    sent = 0
    for user in pro_users:
        try:
            await bot.send_message(chat_id=user["telegram_id"], text=msg)
            sent += 1
        except Exception as e:
            logger.error(f"Daily signal failed for {user['telegram_id']}: {e}")

    logger.info(f"Daily signals sent to {sent} Pro users")