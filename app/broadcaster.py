import logging
import httpx
from app.database import supabase
from app.config import TELEGRAM_BOT_TOKEN
from datetime import datetime, UTC
from app.signal_engine import is_tradeable_equity
import asyncio


logger = logging.getLogger(__name__)

async def _send(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
    except Exception as e:
        logger.error(f"Send failed for {chat_id}: {e}")

def get_active_paid_users(tier_filter: list = None) -> list:
    query = supabase.table("users").select("*")
    if tier_filter:
        query = query.in_("tier", tier_filter)
    result = query.execute()

    active = []
    for user in (result.data or []):
        expires_at = user.get("expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                # make naive datetime timezone-aware
                if exp.tzinfo is None:
                    from datetime import timezone
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > datetime.now(UTC):
                    active.append(user)
            except Exception as e:
                logger.error(f"Date parse error for {user.get('telegram_id')}: {e}")
                continue
    return active

async def broadcast_weekly_signals():
    logger.info("Broadcasting weekly signals...")

    signals_result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute()

    if not signals_result.data:
        logger.info("No signals to broadcast")
        return

    paid_users = get_active_paid_users(["basic", "pro"])

    if not paid_users:
        logger.info("No paid users to broadcast to")
        return

    msg = "📊 Good morning! This week's StockOracle signals are ready.\n\n"
    for i, s in enumerate(signals_result.data, 1):
        msg += (
            f"{i}. {s['ticker']}\n"
            f"Entry: ₦{s['entry_price']}\n"
            f"TP1: ₦{s['tp1']} (+6%)\n"
            f"TP2: ₦{s['tp2']} (+12%)\n"
            f"Stop Loss: ₦{s['stop_loss']}\n\n"
        )
    msg += "⚠️ Always manage your risk. Good luck this week!"

    sent = 0
    for user in paid_users:
        await _send(user["telegram_id"], msg)
        sent += 1

    logger.info(f"Broadcast sent to {sent} users")

async def send_tp_alerts():
    logger.info("Checking take profit alerts...")

    closed = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .is_("alert_sent", "null")\
        .execute()

    if not closed.data:
        return

    paid_users = get_active_paid_users(["basic", "pro"])

    for record in closed.data:
        ticker = record["ticker"]
        
        # skip non-equity tickers silently
        if not is_tradeable_equity(ticker):
            supabase.table("signal_history")\
                .update({"alert_sent": True})\
                .eq("id", record["id"])\
                .execute()
            continue

        outcome = record["outcome"]
        gain = record.get("gain_percentage", 0)

        if outcome == "tp1_hit":
            msg = (
                f"🎯 Take Profit Hit!\n\n"
                f"{ticker} has reached its target price.\n"
                f"Gain: +{gain}%\n\n"
                f"Consider taking profit now or moving your stop loss up to protect gains."
            )
        else:
            msg = (
                f"🛑 Stop Loss Hit\n\n"
                f"{ticker} has hit the stop loss level.\n"
                f"Loss: {gain}%\n\n"
                f"Risk management working as intended. Capital preserved for the next opportunity."
            )

        for user in paid_users:
            await _send(user["telegram_id"], msg)
            await asyncio.sleep(2)

        supabase.table("signal_history")\
            .update({"alert_sent": True})\
            .eq("id", record["id"])\
            .execute()

    logger.info("Take profit alerts done")

async def send_watchlist_updates():
    logger.info("Sending watchlist updates...")

    result = supabase.table("watchlist").select("telegram_id, ticker").execute()
    if not result.data:
        return

    user_tickers = {}
    for row in result.data:
        tid = row["telegram_id"]
        if tid not in user_tickers:
            user_tickers[tid] = []
        user_tickers[tid].append(row["ticker"])

    for telegram_id, tickers in user_tickers.items():
        msg = "📋 Your Watchlist Update\n\n"
        for ticker in tickers:
            stock = supabase.table("stocks")\
                .select("price, change, signal")\
                .eq("ticker", ticker)\
                .order("scraped_at", desc=True)\
                .limit(1)\
                .execute()

            if stock.data:
                s = stock.data[0]
                msg += f"{ticker} — {s['price']} | {s['change']} | {s['signal']}\n"

        await _send(telegram_id, msg)