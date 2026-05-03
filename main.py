import asyncio
from app.scheduler import start_scheduler, scrape_and_save
from telegram.ext import Application, CommandHandler
from app.bot import start, help_command, signals, explain, performance, subscribe
from app.config import TELEGRAM_BOT_TOKEN
from app.signal_engine import run_signal_engine

async def main():
    # run scraper once on startup
    await scrape_and_save()
    run_signal_engine()
    
    # start scheduler
    scheduler = start_scheduler()
    
    # build telegram bot
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("explain", explain))
    app.add_handler(CommandHandler("performance", performance))
    app.add_handler(CommandHandler("subscribe", subscribe))

    print("StockOracle running...")
    
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True:
            await asyncio.sleep(60)

asyncio.run(main())