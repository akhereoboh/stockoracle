import asyncio
from app.scheduler import start_scheduler, scrape_and_save

async def main():
    # run once immediately on startup
    await scrape_and_save()
    
    # then start the scheduler for daily runs
    scheduler = start_scheduler()
    
    print("StockOracle scheduler running...")
    
    # keep the process alive
    while True:
        await asyncio.sleep(60)

asyncio.run(main())