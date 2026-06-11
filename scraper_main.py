import asyncio
import logging
from app.scheduler import start_scheduler, scrape_and_save
from app.signal_engine import run_signal_engine
from app.broadcaster import send_tp_alerts, send_watchlist_updates, get_active_paid_users, _send
from app.daily_signals import broadcast_daily_signals
from app.news_analyzer import run_filings_monitor
from app.hermes import review_signals, monitor_active_signals, weekly_digest
from app.database import supabase
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

async def broadcast_weekly_signals():
    logger.info("Running Monday broadcast with Hermes review...")
    from datetime import date

    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .gte("created_at", date.today().isoformat())\
        .execute()

    signals = result.data or []
    if not signals:
        logger.info("No signals to broadcast")
        return

    approved = await review_signals(signals)
    if not approved:
        logger.info("Hermes rejected all signals — nothing broadcast")
        return

    paid_users = get_active_paid_users(["basic", "pro"])
    if not paid_users:
        return

    msg = "📊 Good morning! This week's StockOracle signals are ready.\n\n"
    for i, s in enumerate(approved, 1):
        msg += (
            f"{i}. {s['ticker']}\n"
            f"Entry: ₦{s['entry_price']}\n"
            f"TP1: ₦{s['tp1']} (+6%)\n"
            f"TP2: ₦{s['tp2']} (+12%)\n"
            f"Stop Loss: ₦{s['stop_loss']}\n\n"
        )
    msg += "⚠️ Always manage your risk. Good luck this week!"

    sent = 0
    for user in paid_users:
        await _send(user["telegram_id"], msg)
        sent += 1

    logger.info(f"Broadcast sent to {sent} users")

async def main():
    await scrape_and_save()
    run_signal_engine()

    scheduler = start_scheduler()

    # monday sequence
    scheduler.add_job(
        scrape_and_save,
        CronTrigger(hour=7, minute=0, day_of_week="mon", timezone="UTC")
    )
    scheduler.add_job(
        run_signal_engine,
        CronTrigger(hour=7, minute=15, day_of_week="mon", timezone="UTC")
    )
    scheduler.add_job(
        broadcast_weekly_signals,
        CronTrigger(hour=7, minute=30, day_of_week="mon", timezone="UTC")
    )

    # tue-fri
    scheduler.add_job(
        scrape_and_save,
        CronTrigger(hour=7, minute=0, day_of_week="tue-fri", timezone="UTC")
    )
    scheduler.add_job(
        broadcast_daily_signals,
        CronTrigger(hour=7, minute=45, day_of_week="tue-fri", timezone="UTC")
    )

    # tp/sl alerts every 30 minutes during market hours
    scheduler.add_job(
        send_tp_alerts,
        CronTrigger(minute="0,30", hour="8-16", day_of_week="mon-fri", timezone="UTC")
    )

    # filings monitor twice daily
    scheduler.add_job(
        run_filings_monitor,
        CronTrigger(hour="8,12", minute=0, day_of_week="mon-fri", timezone="UTC")
    )

    scheduler.add_job(
        send_watchlist_updates,
        CronTrigger(hour=7, minute=30, day_of_week="mon-fri", timezone="UTC")
    )
    scheduler.add_job(
        monitor_active_signals,
        CronTrigger(hour="8-14", minute=30, day_of_week="mon-fri", timezone="UTC")
    )
    scheduler.add_job(
        weekly_digest,
        CronTrigger(hour=15, minute=0, day_of_week="fri", timezone="UTC")
    )

    logger.info("StockOracle scraper and broadcaster running...")
    while True:
        await asyncio.sleep(60)

asyncio.run(main())