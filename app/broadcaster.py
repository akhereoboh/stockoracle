import logging
from app.database import supabase
from app.payments import get_user
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

async def broadcast_weekly_signals(bot):
    logger.info("Broadcasting weekly signals to paid users...")
    
    # get all paid users
    result = supabase.table("users")\
        .select("*")\
        .in_("tier", ["basic", "pro"])\
        .execute()
    
    paid_users = []
    for user in (result.data or []):
        expires_at = user.get("expires_at")
        if expires_at:
            try:
                from datetime import datetime, UTC
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp > datetime.now(UTC):
                    paid_users.append(user)
            except:
                continue
    
    if not paid_users:
        logger.info("No paid users to broadcast to")
        return
    
    # get this week's signals
    signals_result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute()
    
    if not signals_result.data:
        logger.info("No signals to broadcast")
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
        try:
            await bot.send_message(chat_id=user["telegram_id"], text=msg)
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send to {user['telegram_id']}: {e}")
    
    logger.info(f"Broadcast sent to {sent} users")

async def send_tp_alerts(bot):
    logger.info("Checking take profit alerts...")
    
    # get recently closed signals
    closed = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .is_("alert_sent", "null")\
        .execute()
    
    if not closed.data:
        return
    
    # get all paid users
    users_result = supabase.table("users")\
        .select("*")\
        .in_("tier", ["basic", "pro"])\
        .execute()
    
    paid_users = users_result.data or []
    
    for record in closed.data:
        ticker = record["ticker"]
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
                f"This is risk management working as intended. Capital preserved for the next opportunity."
            )
        
        for user in paid_users:
            try:
                await bot.send_message(chat_id=user["telegram_id"], text=msg)
            except Exception as e:
                logger.error(f"Alert failed for {user['telegram_id']}: {e}")
        
        # mark alert as sent
        supabase.table("signal_history")\
            .update({"alert_sent": True})\
            .eq("id", record["id"])\
            .execute()

    logger.info("Take profit alerts done")