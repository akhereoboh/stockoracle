import asyncio
import threading
from app.scheduler import start_scheduler, scrape_and_save
from app.bot import run_bot

async def main():
    await scrape_and_save()
    scheduler = start_scheduler()
    print("StockOracle scheduler running...")
    
    # run bot in separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    while True:
        await asyncio.sleep(60)

asyncio.run(main())