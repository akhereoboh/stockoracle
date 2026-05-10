import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from app.config import TELEGRAM_BOT_TOKEN, PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN
from app.database import supabase
from app.payments import register_user, get_user, create_subscription_link
from app.ai import get_ai_response
from datetime import datetime, UTC

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_histories = {}

def is_paid(user: dict) -> bool:
    if not user:
        return False
    if user.get("tier") not in ["basic", "pro"]:
        return False
    expires_at = user.get("expires_at")
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return exp > datetime.now(UTC)
    except:
        return False

def is_pro(user: dict) -> bool:
    if not is_paid(user):
        return False
    return user.get("tier") == "pro"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    name = update.effective_user.first_name or "there"
    
    register_user(telegram_id, name)
    
    await update.message.reply_text(
        f"👋 Welcome to StockOracle, {name}!\n\n"
        "I'm your AI-powered Nigerian stock market analyst. "
        "I scan 450+ NGX stocks daily and find the best opportunities for you.\n\n"
        "What I can do:\n"
        "- Weekly top 5 NGX stock signals with entry, take profit and stop loss\n"
        "- Real-time stock prices and analysis\n"
        "- AI conversation about any stock or market question\n"
        "- Chart and screenshot analysis\n"
        "- Take profit alerts when your stocks hit targets\n\n"
        "Commands:\n"
        "/signals — this week's top picks\n"
        "/explain GTCO — analyse any stock\n"
        "/subscribe — unlock full access\n"
        "/performance — our track record\n"
        "/help — all commands\n\n"
        "Try asking me anything about Nigerian stocks!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "StockOracle Commands:\n\n"
        "/signals — weekly stock picks\n"
        "/explain [TICKER] — deep analysis of any stock\n"
        "/performance — signal track record\n"
        "/subscribe — view plans and subscribe\n"
        "/mystatus — check your subscription\n"
        "/clear — reset conversation\n\n"
        "Or just chat with me naturally about any stock!"
    )

async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute()
    
    if not result.data:
        await update.message.reply_text("No active signals yet. Check back Monday!")
        return
    
    if not is_paid(user):
        # free users see only first signal, rest blurred
        signal = result.data[0]
        msg = (
            "📊 This Week's NGX Signals\n\n"
            f"1. {signal['ticker']}\n"
            f"Entry: ₦{signal['entry_price']}\n"
            f"TP1: ₦{signal['tp1']} (+6%)\n"
            f"TP2: ₦{signal['tp2']} (+12%)\n"
            f"Stop Loss: ₦{signal['stop_loss']}\n\n"
            "🔒 Signals 2-5 are locked.\n"
            "Subscribe to unlock all signals, take profit alerts, and AI analysis.\n\n"
            "Use /subscribe to get full access."
        )
        await update.message.reply_text(msg)
        return
    
    msg = "📊 This Week's Top 5 NGX Signals\n\n"
    for i, s in enumerate(result.data, 1):
        msg += (
            f"{i}. {s['ticker']}\n"
            f"Entry: ₦{s['entry_price']}\n"
            f"TP1: ₦{s['tp1']} (+6%)\n"
            f"TP2: ₦{s['tp2']} (+12%)\n"
            f"Stop Loss: ₦{s['stop_loss']}\n\n"
        )
    
    msg += "⚠️ Always manage your risk. Never invest more than you can afford to lose."
    await update.message.reply_text(msg)

async def explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    args = context.args
    
    if not args:
        await update.message.reply_text("Usage: /explain GTCO")
        return
    
    # free users: check daily limit
    if not is_paid(user):
        today_key = f"explain_{telegram_id}_{datetime.now(UTC).date()}"
        count = context.bot_data.get(today_key, 0)
        if count >= 2:
            await update.message.reply_text(
                "You've used your 2 free lookups today.\n"
                "Subscribe to get unlimited lookups.\n\n"
                "Use /subscribe to upgrade."
            )
            return
        context.bot_data[today_key] = count + 1
    
    ticker = args[0].upper()
    result = supabase.table("stocks")\
        .select("*")\
        .eq("ticker", ticker)\
        .order("scraped_at", desc=True)\
        .limit(1)\
        .execute()
    
    if not result.data:
        await update.message.reply_text(f"Ticker {ticker} not found.")
        return
    
    stock = result.data[0]
    await update.message.reply_text(
        f"📊 {stock['ticker']} — {stock['company']}\n\n"
        f"Price: {stock['price']}\n"
        f"Change: {stock['change']}\n"
        f"Signal: {stock['signal']}\n"
        f"Volume: {stock['volume']}\n\n"
        f"Ask me anything about this stock for deeper analysis."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Basic — ₦5,999/month", callback_data="subscribe_basic")],
        [InlineKeyboardButton("Pro — ₦9,999/month", callback_data="subscribe_pro")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "StockOracle Plans:\n\n"
        "Basic — ₦5,999/month\n"
        "- All 5 weekly signals in real time\n"
        "- Take profit and stop loss alerts\n"
        "- Unlimited stock lookups\n"
        "- AI market analysis\n\n"
        "Pro — ₦9,999/month\n"
        "- Everything in Basic\n"
        "- Daily signals (not just weekly)\n"
        "- Portfolio audit\n"
        "- Priority AI responses\n"
        "- Full performance track record\n\n"
        "Choose your plan:",
        reply_markup=reply_markup
    )

async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    
    await query.edit_message_text(
        "To complete your subscription, I need your email address.\n\n"
        "Please reply with your email:"
    )
    
    plan = "basic" if query.data == "subscribe_basic" else "pro"
    context.user_data["pending_plan"] = plan

async def handle_email_for_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    pending_plan = context.user_data.get("pending_plan")
    
    if not pending_plan:
        return False
    
    email = update.message.text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("That doesn't look like a valid email. Please try again.")
        return True
    
    plan_code = PAYSTACK_BASIC_PLAN if pending_plan == "basic" else PAYSTACK_PRO_PLAN
    link = create_subscription_link(email, plan_code, telegram_id)
    
    if not link:
        await update.message.reply_text("Something went wrong generating your payment link. Please try /subscribe again.")
        context.user_data.pop("pending_plan", None)
        return True
    
    context.user_data.pop("pending_plan", None)
    
    tier_name = "Basic" if pending_plan == "basic" else "Pro"
    amount = "₦5,999" if pending_plan == "basic" else "₦9,999"
    
    await update.message.reply_text(
        f"Your {tier_name} payment link is ready.\n\n"
        f"Amount: {amount}/month\n\n"
        f"Click here to pay:\n{link}\n\n"
        "Your account will be upgraded automatically once payment is confirmed."
    )
    return True

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("You are not registered yet. Send /start to begin.")
        return
    
    tier = user.get("tier", "free").capitalize()
    
    if is_paid(user):
        expires = user.get("expires_at", "")[:10]
        await update.message.reply_text(
            f"Your subscription: {tier}\n"
            f"Active until: {expires}\n\n"
            "Enjoying StockOracle? Tell a friend!"
        )
    else:
        await update.message.reply_text(
            f"Your plan: Free\n\n"
            "You're on the free tier. Upgrade to unlock:\n"
            "- All 5 weekly signals\n"
            "- Take profit alerts\n"
            "- Unlimited AI analysis\n\n"
            "Use /subscribe to upgrade."
        )

async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .order("closed_at", desc=True)\
        .limit(20)\
        .execute()
    
    if not result.data:
        await update.message.reply_text(
            "Track record is building. Check back after our first signals close.\n\n"
            "Every signal outcome is recorded automatically — wins and losses both."
        )
        return
    
    records = result.data
    wins = [r for r in records if r["outcome"] == "tp1_hit"]
    losses = [r for r in records if r["outcome"] == "stopped_out"]
    win_rate = round(len(wins) / len(records) * 100) if records else 0
    avg_gain = round(sum(r["gain_percentage"] for r in records) / len(records), 2) if records else 0
    
    msg = (
        f"📈 StockOracle Track Record\n\n"
        f"Total signals closed: {len(records)}\n"
        f"Win rate: {win_rate}%\n"
        f"Average gain/loss: {avg_gain}%\n"
        f"Wins: {len(wins)} | Losses: {len(losses)}\n\n"
        "Recent signals:\n"
    )
    
    for r in records[:5]:
        emoji = "✅" if r["outcome"] == "tp1_hit" else "❌"
        msg += f"{emoji} {r['ticker']} — {r['gain_percentage']}%\n"
    
    await update.message.reply_text(msg)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_histories:
        del user_histories[user_id]
    await update.message.reply_text("Conversation cleared. Fresh start!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "there"
    user_message = update.message.text or ""
    image_data = None
    image_mime = None

    # check if user is providing email for subscription
    if context.user_data.get("pending_plan"):
        handled = await handle_email_for_subscription(update, context)
        if handled:
            return

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_data = await file.download_as_bytearray()
        image_mime = "image/jpeg"
        user_message = update.message.caption or ""

    user = get_user(user_id)
    if not is_paid(user):
        # free users: limit AI messages to 5 per day
        today_key = f"ai_{user_id}_{datetime.now(UTC).date()}"
        count = context.bot_data.get(today_key, 0)
        if count >= 5:
            await update.message.reply_text(
                "You've used your 5 free AI messages today.\n"
                "Subscribe for unlimited AI analysis.\n\n"
                "Use /subscribe to upgrade."
            )
            return
        context.bot_data[today_key] = count + 1

    if user_id not in user_histories:
        user_histories[user_id] = []

    thinking_msg = await update.message.reply_text("🤔 Analysing...")

    response, updated_history = get_ai_response(
        user_message, user_name, image_data, image_mime, user_histories[user_id]
    )

    user_histories[user_id] = updated_history[-20:]

    await thinking_msg.delete()
    await update.message.reply_text(response)

def run_bot():
    return Application.builder().token(TELEGRAM_BOT_TOKEN).build()