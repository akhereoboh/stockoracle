import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.database import supabase
from app.payments import upgrade_user, get_user
from datetime import datetime, UTC, timedelta
import asyncio
import httpx
from app.config import TELEGRAM_BOT_TOKEN
from datetime import timezone

logger = logging.getLogger(__name__)

ADMIN_IDS = [1696237112]  # your telegram ID

def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS

async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
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


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "/broadcast all Your message here\n"
            "/broadcast lite Your message here\n"
            "/broadcast basic Your message here\n"
            "/broadcast pro Your message here\n"
            "/broadcast paid Your message here"
        )
        return

    tier_filter = args[0].lower()
    message = " ".join(args[1:])

    if not message:
        await update.message.reply_text("Please include a message after the tier.")
        return

    # get recipients based on tier
    if tier_filter == "all":
        result = supabase.table("users").select("telegram_id, name").execute()
        recipients = result.data or []
    elif tier_filter == "paid":
        result = supabase.table("users").select("telegram_id, name, tier, expires_at").execute()
        from datetime import timezone
        recipients = []
        for u in (result.data or []):
            if u.get("tier") in ["basic", "pro"] and u.get("expires_at"):
                try:
                    exp = datetime.fromisoformat(u["expires_at"].replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp > datetime.now(UTC):
                        recipients.append(u)
                except:
                    pass
    else:
        # specific tier
        result = supabase.table("users").select("telegram_id, name, tier, expires_at").eq("tier", tier_filter).execute()
       
        recipients = []
        for u in (result.data or []):
            if u.get("expires_at"):
                try:
                    exp = datetime.fromisoformat(u["expires_at"].replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp > datetime.now(UTC):
                        recipients.append(u)
                except:
                    pass
            elif tier_filter not in ["basic", "pro"]:
                recipients.append(u)

    if not recipients:
        await update.message.reply_text(f"No users found for tier: {tier_filter}")
        return

    await update.message.reply_text(f"📤 Starting broadcast to {len(recipients)} users...")

    
    sent = 0
    failed = 0
    failed_ids = []

    async with httpx.AsyncClient() as client:
        for i, user in enumerate(recipients):
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": user["telegram_id"], "text": message},
                    timeout=10
                )
                sent += 1
            except Exception as e:
                failed += 1
                failed_ids.append(user["telegram_id"])
                logger.error(f"Broadcast failed for {user['telegram_id']}: {e}")
            
            await asyncio.sleep(0.3)
            
            # progress update every 50 users
            if (i + 1) % 50 == 0:
                await update.message.reply_text(
                    f"⏳ Progress: {i+1}/{len(recipients)} — "
                    f"Sent: {sent} | Failed: {failed}"
                )

    # final confirmation
    summary = (
        f"✅ Broadcast complete!\n\n"
        f"Tier targeted: {tier_filter}\n"
        f"Total recipients: {len(recipients)}\n"
        f"Successfully sent: {sent}\n"
        f"Failed: {failed}\n"
    )

    if failed_ids:
        summary += f"\nFailed IDs: {', '.join(str(i) for i in failed_ids[:10])}"
        if len(failed_ids) > 10:
            summary += f" and {len(failed_ids) - 10} more"

    await update.message.reply_text(summary)


async def launch_waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return

    result = supabase.table("users")\
        .select("*")\
        .eq("waitlist", True)\
        .eq("waitlist_notified", False)\
        .execute()

    users = result.data or []
    if not users:
        await update.message.reply_text("No waitlist users to notify.")
        return

    await update.message.reply_text(f"🚀 Notifying {len(users)} waitlist users...")

    sent = 0
    failed = 0

    launch_msg = (
        "🎉 *StockOracle is LIVE\\!*\n\n"
        "Your early access is ready\\. As a founding member your discount is locked in:\n\n"
        "Premium: ~₦25,000/month~ ➡️ *₦9,999/month*\n"
        "Pro: ~₦10,000/month~ ➡️ *₦5,999/month*\n\n"
        "This price is yours forever as long as you stay subscribed\\.\n\n"
        "Type /start to accept terms and get full access now\\!\n\n"
        "Welcome to the future of Nigerian stock investing 🚀"
    )

    async with httpx.AsyncClient() as client:
        for user in users:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": user["telegram_id"],
                        "text": launch_msg,
                        "parse_mode": "MarkdownV2"
                    },
                    timeout=10
                )
                supabase.table("users").update({
                    "waitlist": False,
                    "waitlist_notified": True
                }).eq("telegram_id", user["telegram_id"]).execute()
                sent += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                failed += 1
                logger.error(f"Launch notify failed for {user['telegram_id']}: {e}")

    await update.message.reply_text(
        f"✅ Launch complete\\!\n\nNotified: {sent}\nFailed: {failed}",
        parse_mode="MarkdownV2"
    )