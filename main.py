import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from app.bot import start, help_command, signals, explain, performance, subscribe, handle_message
from app.config import TELEGRAM_BOT_TOKEN

async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("explain", explain))
    app.add_handler(CommandHandler("performance", performance))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_message))

    print("StockOracle bot running...")
    async with app:
        await app.start()
        await app.updater.start_polling()
        while True:
            await asyncio.sleep(60)

asyncio.run(main())