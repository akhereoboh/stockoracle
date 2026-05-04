from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.scrapers.ngx import get_ngx_prices
from app.database import supabase
from datetime import datetime, UTC
import asyncio
import logging
from datetime import date

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

def start_scheduler():
    scheduler = AsyncIOScheduler()
    
    # runs every weekday at 9am and 2pm Nigerian time (WAT = UTC+1)
    scheduler.add_job(scrape_and_save, CronTrigger(
        hour=8, minute=0, day_of_week="mon-fri", timezone="UTC"
    ))
    scheduler.add_job(scrape_and_save, CronTrigger(
        hour=13, minute=30, day_of_week="mon-fri", timezone="UTC"
    ))
    
    scheduler.start()
    return scheduler