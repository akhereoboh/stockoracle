import asyncio
import threading
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from app.bot import (start, help_command, signals, explain, performance,
                     subscribe, subscribe_callback, terms_callback, my_status,
                     clear, handle_message, audit, watchlist_add,
                     watchlist_view, watchlist_remove, referral, cancel, run_bot)
from app.admin import analytics, admin_upgrade, admin_downgrade, admin_users
from app.config import TELEGRAM_BOT_TOKEN
from app.scheduler import start_scheduler
from app.broadcaster import broadcast_weekly_signals, send_tp_alerts, send_watchlist_updates
from app.daily_signals import broadcast_daily_signals
from app.news_analyzer import run_news_monitor
import uvicorn
from app.webhook import webhook_app
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

def make_async_job(coro_func):
    def job():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro_func())
        finally:
            loop.close()
    return job

async def main():
    application = run_bot()

    # user commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("signals", signals))
    application.add_handler(CommandHandler("explain", explain))
    application.add_handler(CommandHandler("performance", performance))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("mystatus", my_status))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("audit", audit))
    application.add_handler(CommandHandler("watch", watchlist_add))
    application.add_handler(CommandHandler("watchlist", watchlist_view))
    application.add_handler(CommandHandler("unwatch", watchlist_remove))
    application.add_handler(CommandHandler("referral", referral))

    # admin commands
    application.add_handler(CommandHandler("analytics", analytics))
    application.add_handler(CommandHandler("adminupgrade", admin_upgrade))
    application.add_handler(CommandHandler("admindowngrade", admin_downgrade))
    application.add_handler(CommandHandler("adminusers", admin_users))

    # callbacks
    application.add_handler(CallbackQueryHandler(terms_callback, pattern="^(accept|decline)_terms$"))
    application.add_handler(CallbackQueryHandler(subscribe_callback, pattern="^(subscribe_|pay_)"))

    # messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))

    scheduler = start_scheduler()

    # define async jobs
    async def monday_broadcast():
        await broadcast_weekly_signals(application.bot)

    async def daily_tp():
        await send_tp_alerts(application.bot)

    async def daily_pro():
        await broadcast_daily_signals(application.bot)

    async def news_check():
        await run_news_monitor(application.bot)

    async def watchlist_update():
        await send_watchlist_updates(application.bot)

    # schedule all jobs with proper async handling
    scheduler.add_job(
        make_async_job(monday_broadcast),
        CronTrigger(hour=7, minute=30, day_of_week="mon", timezone="UTC")
    )
    scheduler.add_job(
        make_async_job(daily_tp),
        CronTrigger(hour=13, minute=50, day_of_week="mon-fri", timezone="UTC")
    )
    scheduler.add_job(
        make_async_job(daily_pro),
        CronTrigger(hour=7, minute=45, day_of_week="tue-fri", timezone="UTC")
    )
    scheduler.add_job(
        make_async_job(news_check),
        CronTrigger(hour="8-14", minute=0, day_of_week="mon-fri", timezone="UTC")
    )
    scheduler.add_job(
        make_async_job(watchlist_update),
        CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone="UTC")
    )

    # webhook server in background thread
    def run_webhook():
        uvicorn.run(webhook_app, host="0.0.0.0", port=8001, log_level="warning")

    webhook_thread = threading.Thread(target=run_webhook, daemon=True)
    webhook_thread.start()
    logger.info("Webhook server running on port 8001")

    print("StockOracle running...")

    async with application:
        await application.start()
        await application.updater.start_polling()
        while True:
            await asyncio.sleep(60)

asyncio.run(main())