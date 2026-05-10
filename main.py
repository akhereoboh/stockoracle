import asyncio
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from app.bot import (start, help_command, signals, explain, performance,
                     subscribe, subscribe_callback, my_status, clear, handle_message, run_bot)
from app.config import TELEGRAM_BOT_TOKEN
from app.scheduler import start_scheduler
from app.broadcaster import broadcast_weekly_signals, send_tp_alerts
import uvicorn
from app.webhook import webhook_app
import logging
from app.bot import audit

logger = logging.getLogger(__name__)

async def main():
    # build telegram app
    application = run_bot()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("signals", signals))
    application.add_handler(CommandHandler("explain", explain))
    application.add_handler(CommandHandler("performance", performance))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("mystatus", my_status))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("audit", audit))
    application.add_handler(CallbackQueryHandler(subscribe_callback, pattern="^subscribe_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))

    # start scheduler with broadcaster
    scheduler = start_scheduler()

    # add broadcast jobs to scheduler
    from apscheduler.triggers.cron import CronTrigger

    async def monday_broadcast():
        await broadcast_weekly_signals(application.bot)

    async def daily_tp_check():
        await send_tp_alerts(application.bot)

    scheduler.add_job(
        lambda: asyncio.create_task(monday_broadcast()),
        CronTrigger(hour=7, minute=30, day_of_week="mon", timezone="UTC")
    )
    scheduler.add_job(
        lambda: asyncio.create_task(daily_tp_check()),
        CronTrigger(hour=13, minute=50, day_of_week="mon-fri", timezone="UTC")
    )

    # run webhook server in background thread
    def run_webhook():
        uvicorn.run(webhook_app, host="0.0.0.0", port=8001, log_level="warning")

    webhook_thread = threading.Thread(target=run_webhook, daemon=True)
    webhook_thread.start()
    logger.info("Webhook server running on port 8001")

    print("StockOracle bot running...")

    async with application:
        await application.start()
        await application.updater.start_polling()
        while True:
            await asyncio.sleep(60)

asyncio.run(main())