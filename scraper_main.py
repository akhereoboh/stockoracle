import asyncio
from app.scheduler import start_scheduler, scrape_and_save
from app.signal_engine import run_signal_engine
from app.broadcaster import broadcast_weekly_signals, send_tp_alerts, send_watchlist_updates
from app.daily_signals import broadcast_daily_signals
from app.news_analyzer import run_news_monitor
from apscheduler.triggers.cron import CronTrigger
import logging

logger = logging.getLogger(__name__)

async def main():
    await scrape_and_save()
    run_signal_engine()
    
    scheduler = start_scheduler()

    # monday: generate signals at 7:00, broadcast at 7:30
    scheduler.add_job(
        run_signal_engine,
        CronTrigger(hour=7, minute=0, day_of_week="mon", timezone="UTC")
    )
    scheduler.add_job(
        broadcast_weekly_signals,
        CronTrigger(hour=7, minute=30, day_of_week="mon", timezone="UTC")
    )
    
    # daily pro signals tue-fri at 7:45am UTC (8:45am Nigerian)
    scheduler.add_job(
        broadcast_daily_signals,
        CronTrigger(hour=7, minute=45, day_of_week="tue-fri", timezone="UTC")
    )
    
    # take profit check after market closes
    scheduler.add_job(
        send_tp_alerts,
        CronTrigger(hour=13, minute=50, day_of_week="mon-fri", timezone="UTC")
    )
    
    # news monitor every hour during market hours
    scheduler.add_job(
        run_news_monitor,
        CronTrigger(hour="8-14", minute=0, day_of_week="mon-fri", timezone="UTC")
    )
    
    # watchlist updates 8:30am Nigerian time
    scheduler.add_job(
        send_watchlist_updates,
        CronTrigger(hour=7, minute=30, day_of_week="mon-fri", timezone="UTC")
    )

    logger.info("StockOracle scraper and broadcaster running...")
    while True:
        await asyncio.sleep(60)

asyncio.run(main())