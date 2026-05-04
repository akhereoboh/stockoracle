import asyncio
from app.scheduler import start_scheduler, scrape_and_save
from app.signal_engine import run_signal_engine

async def main():
    await scrape_and_save()
    run_signal_engine()
    scheduler = start_scheduler()
    print("StockOracle scraper running...")
    while True:
        await asyncio.sleep(60)

asyncio.run(main())