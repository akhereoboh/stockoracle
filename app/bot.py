import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from app.config import TELEGRAM_BOT_TOKEN
from app.database import supabase
from app.ai import get_ai_response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to StockOracle!\n\n"
        "I help you find the best Nigerian stocks to trade.\n\n"
        "Commands:\n"
        "/signals — this week's top picks\n"
        "/explain GTCO — explain any stock\n"
        "/watchlist — your saved stocks\n"
        "/performance — our track record\n"
        "/help — show this menu"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 StockOracle Commands:\n\n"
        "/signals — weekly stock picks\n"
        "/explain [TICKER] — AI explanation of any stock\n"
        "/watchlist — manage your watchlist\n"
        "/performance — signal track record\n"
        "/subscribe — view plans"
    )

async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute()
    
    if not result.data:
        await update.message.reply_text("No active signals yet. Check back Monday!")
        return
    
    msg = "📊 *This Week's Top 5 NGX Signals*\n\n"
    
    for i, s in enumerate(result.data, 1):
        msg += f"{i}. *{s['ticker']}*\n"
        msg += f"   Entry: ₦{s['entry_price']}\n"
        msg += f"   TP1: ₦{s['tp1']} (+6%)\n"
        msg += f"   TP2: ₦{s['tp2']} (+12%)\n"
        msg += f"   Stop Loss: ₦{s['stop_loss']}\n\n"
    
    msg += "⚠️ Always manage your risk. Never invest more than you can afford to lose."
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /explain GTCO")
        return
    
    ticker = args[0].upper()
    
    # fetch latest price from supabase
    result = supabase.table("stocks")\
        .select("*")\
        .eq("ticker", ticker)\
        .order("scraped_at", desc=True)\
        .limit(1)\
        .execute()
    
    if not result.data:
        await update.message.reply_text(f"❌ Ticker {ticker} not found.")
        return
    
    stock = result.data[0]
    await update.message.reply_text(
        f"📊 {stock['ticker']} — {stock['company']}\n\n"
        f"Price: {stock['price']}\n"
        f"Change: {stock['change']}\n"
        f"Signal: {stock['signal']}\n\n"
        f"AI analysis coming soon in Pro tier."
    )

async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 Track Record\n\n"
        "Signal history will appear here once we have enough data.\n"
        "Check back after our first week of signals!"
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 StockOracle Plans\n\n"
        "🆓 Free — 2 stock lookups/day, delayed signals\n"
        "📊 Basic ₦2,500/month — real-time signals + alerts\n"
        "🚀 Pro ₦7,500/month — daily signals + portfolio audit\n\n"
        "Payment coming soon via Paystack."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or "there"
    user_message = update.message.text or ""
    image_data = None
    image_mime = None

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_data = await file.download_as_bytearray()
        image_mime = "image/jpeg"
        user_message = update.message.caption or ""

    thinking_msg = await update.message.reply_text("🤔 Analysing...")

    response = get_ai_response(user_message, user_name, image_data, image_mime)
    
    await thinking_msg.delete()
    await update.message.reply_text(response)



def run_bot():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("explain", explain))
    app.add_handler(CommandHandler("performance", performance))
    app.add_handler(CommandHandler("subscribe", subscribe))
    
    logger.info("StockOracle bot started...")
    app.run_polling()