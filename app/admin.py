import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.database import supabase
from app.payments import upgrade_user, get_user
from datetime import datetime, UTC, timedelta

logger = logging.getLogger(__name__)

ADMIN_IDS = [1696237112]  # your telegram ID

def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    users = supabase.table("users").select("*").execute()
    all_users = users.data or []

    total = len(all_users)
    free = sum(1 for u in all_users if u.get("tier") == "free")
    basic = sum(1 for u in all_users if u.get("tier") == "basic")
    pro = sum(1 for u in all_users if u.get("tier") == "pro")

    active_basic = 0
    active_pro = 0
    for u in all_users:
        expires = u.get("expires_at")
        if expires:
            try:
                exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp > datetime.now(UTC):
                    if u.get("tier") == "basic":
                        active_basic += 1
                    elif u.get("tier") == "pro":
                        active_pro += 1
            except:
                pass

    monthly_revenue = (active_basic * 5999) + (active_pro * 9999)

    signals = supabase.table("signals").select("id").execute()
    news = supabase.table("news_alerts").select("id").execute()

    await update.message.reply_text(
        f"StockOracle Admin Stats\n\n"
        f"Total users: {total}\n"
        f"Free: {free}\n"
        f"Basic (active): {active_basic}\n"
        f"Pro (active): {active_pro}\n\n"
        f"Monthly revenue: ₦{monthly_revenue:,}\n\n"
        f"Total signals generated: {len(signals.data or [])}\n"
        f"News alerts stored: {len(news.data or [])}\n\n"
        f"Commands:\n"
        f"/adminupgrade [telegram_id] [basic/pro]\n"
        f"/admindowngrade [telegram_id]\n"
        f"/adminusers — list recent users"
    )

async def admin_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /adminupgrade [telegram_id] [basic/pro]")
        return

    try:
        tid = int(args[0])
        tier = args[1].lower()
        if tier not in ["basic", "pro"]:
            await update.message.reply_text("Tier must be basic or pro")
            return

        user = get_user(tid)
        if not user:
            await update.message.reply_text(f"User {tid} not found")
            return

        upgrade_user(tid, tier)
        await update.message.reply_text(f"User {tid} upgraded to {tier}")

        # notify user
        await context.bot.send_message(
            chat_id=tid,
            text=f"Your StockOracle account has been upgraded to {tier.capitalize()} by admin."
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_downgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /admindowngrade [telegram_id]")
        return

    try:
        tid = int(args[0])
        supabase.table("users").update({"tier": "free"}).eq("telegram_id", tid).execute()
        await update.message.reply_text(f"User {tid} downgraded to free")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    result = supabase.table("users")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()

    users = result.data or []
    if not users:
        await update.message.reply_text("No users yet")
        return

    msg = f"Recent users ({len(users)}):\n\n"
    for u in users:
        expires = u.get("expires_at", "")[:10] if u.get("expires_at") else "—"
        msg += f"{u['name']} | {u['tier']} | expires: {expires} | ID: {u['telegram_id']}\n"

    await update.message.reply_text(msg)