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
import uvicorn
from app.webhook import webhook_app
from app.admin import analytics, admin_upgrade, admin_downgrade, admin_users, admin_broadcast

from app.admin import analytics, admin_upgrade, admin_downgrade, admin_users, admin_broadcast, launch_waitlist
from app.bot import (start, help_command, signals, explain, performance,
                     subscribe, subscribe_callback, terms_callback, my_status,
                     clear, handle_message, audit, watchlist_add,
                     watchlist_view, watchlist_remove, referral, cancel, run_bot,
                     LAUNCH_DATE, EXISTING_USER_IDS, WAITLIST_BLOCK_MSG)
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import date
from app.bot import copy_trading
# from app.admin import analytics, admin_upgrade, admin_downgrade, admin_users, admin_broadcast, launch_waitlist,
from app.admin import (analytics, admin_upgrade, admin_downgrade, admin_users, 
                        admin_broadcast, launch_waitlist, mark_referral_paid)
from app.admin import (analytics, admin_upgrade, admin_downgrade, admin_users,
                        admin_broadcast, launch_waitlist, referral_report, 
                        mark_referral_paid, view_conversations)


logger = logging.getLogger(__name__)

async def main():
    application = run_bot()

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
    application.add_handler(CommandHandler("analytics", analytics))
    application.add_handler(CommandHandler("adminupgrade", admin_upgrade))
    application.add_handler(CommandHandler("admindowngrade", admin_downgrade))
    application.add_handler(CommandHandler("adminusers", admin_users))

    application.add_handler(CallbackQueryHandler(terms_callback, pattern="^(accept|decline)_terms$"))
    application.add_handler(CallbackQueryHandler(subscribe_callback, pattern="^(subscribe_|pay_)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))

    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("launchwaitlist", launch_waitlist))
    application.add_handler(CommandHandler("copytrading", copy_trading))
    application.add_handler(CommandHandler("referralreport", referral_report))
    application.add_handler(CommandHandler("markpaid", mark_referral_paid))
    application.add_handler(CommandHandler("conversations", view_conversations))


    # catch-all for waitlist users trying any command
    async def waitlist_catch(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        today = date.today()
        if today < LAUNCH_DATE and telegram_id not in EXISTING_USER_IDS:
            user = get_user(telegram_id)
            if user and user.get("waitlist"):
                await update.message.reply_text(WAITLIST_BLOCK_MSG, parse_mode="MarkdownV2")

    from app.bot import get_user
    application.add_handler(MessageHandler(filters.COMMAND, waitlist_catch))
    
    def run_webhook():
        uvicorn.run(webhook_app, host="0.0.0.0", port=7001, log_level="warning")

    webhook_thread = threading.Thread(target=run_webhook, daemon=True)
    webhook_thread.start()
    logger.info("Webhook server running on port 7001")

    print("StockOracle bot running...")

    async with application:
        await application.start()
        await application.updater.start_polling()
        while True:
            await asyncio.sleep(60)

asyncio.run(main())