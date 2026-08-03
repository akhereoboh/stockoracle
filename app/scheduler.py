from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.scrapers.ngx import get_ngx_prices
from app.database import supabase
from app.signal_engine import run_signal_engine, update_signal_outcomes
from datetime import datetime, UTC, date
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def scrape_and_save():
    try:
        logger.info("Starting NGX scrape...")
        stocks = await get_ngx_prices()

        for stock in stocks:
            stock["scraped_at"] = datetime.now(UTC).isoformat()
            stock["trade_date"] = date.today().isoformat()

        supabase.table("stocks").upsert(
            stocks, on_conflict="ticker,trade_date"
        ).execute()
        logger.info(f"Saved {len(stocks)} stocks to Supabase")
    except Exception as e:
        logger.error(f"Scrape failed: {e}")

def generate_weekly_signals():
    try:
        logger.info("Generating weekly signals...")
        run_signal_engine()
    except Exception as e:
        logger.error(f"Signal engine failed: {e}")

def check_outcomes():
    try:
        update_signal_outcomes()
    except Exception as e:
        logger.error(f"Outcome check failed: {e}")

def start_scheduler():
    scheduler = AsyncIOScheduler()

    # scrape twice daily on weekdays
    scheduler.add_job(scrape_and_save, CronTrigger(
        hour=8, minute=0, day_of_week="mon-fri", timezone="UTC"
    ))
    scheduler.add_job(scrape_and_save, CronTrigger(
        hour=13, minute=30, day_of_week="mon-fri", timezone="UTC"
    ))

   

    # check signal outcomes every weekday at 2:45pm Nigerian time
    scheduler.add_job(check_outcomes, CronTrigger(
        hour=13, minute=45, day_of_week="mon-fri", timezone="UTC"
    ))

    scheduler.start()
    return scheduler