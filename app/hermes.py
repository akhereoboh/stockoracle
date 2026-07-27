import logging
import httpx
import anthropic
from app.database import supabase
from app.config import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
from datetime import datetime, UTC, date, timedelta

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ADMIN_TELEGRAM_ID = 1696237112

async def send_hermes_alert(text: str):
    try:
        async with httpx.AsyncClient() as http:
            await http.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_TELEGRAM_ID,
                    "text": f"🔮 Hermes\n\n{text}"
                },
                timeout=10
            )
    except Exception as e:
        logger.error(f"Hermes alert error: {e}")

from app.news_analyzer import get_recent_filings_for_hermes

async def review_signals(signals: list) -> list:
    if not signals:
        return []

    logger.info(f"Hermes reviewing {len(signals)} signals...")

    # deduplicate by ticker
    seen = {}
    for s in signals:
        ticker = s["ticker"]
        if ticker not in seen:
            seen[ticker] = s
    unique_signals = list(seen.values())

    if len(unique_signals) < len(signals):
        logger.info(f"Removed {len(signals) - len(unique_signals)} duplicate signals")

    # get market breadth
    stocks_result = supabase.table("stocks")\
        .select("change")\
        .eq("trade_date", date.today().isoformat())\
        .execute()
    stocks = stocks_result.data or []
    if stocks:
        up = sum(1 for s in stocks if s.get("change", "").strip("'\" ").startswith("+") 
                 and s.get("change", "").strip("'\" ") != "+0.00%")
        breadth = up / len(stocks) * 100
    else:
        breadth = 50

    # reject if breadth too low
    if breadth < 40:
        msg = f"Signal Audit\n\nAll signals paused — market breadth too low ({breadth:.1f}%)"
        await send_hermes_alert(msg)
        return []

    # get recent negative filings
    filings_result = supabase.table("filings")\
        .select("ticker, sentiment, impact, summary")\
        .eq("sentiment", "negative")\
        .in_("impact", ["high", "medium"])\
        .gte("scraped_at", (datetime.now(UTC) - timedelta(days=2)).isoformat())\
        .execute()

    negative_tickers = {f["ticker"] for f in (filings_result.data or []) if f.get("ticker")}

    approved = []
    rejected = []
    for s in unique_signals:
        if s["ticker"] in negative_tickers:
            rejected.append(f"{s['ticker']}: REJECT — negative filing detected")
        else:
            approved.append(s)

    msg = (
        f"Signal Audit\n\n"
        f"Proposed: {len(signals)} | Unique: {len(unique_signals)} | "
        f"Approved: {len(approved)} | Rejected: {len(rejected)}\n"
        f"Market breadth: {breadth:.1f}%\n\n"
    )
    if rejected:
        msg += "Rejected:\n" + "\n".join(rejected)
    if approved:
        msg += "\nApproved: " + ", ".join(s["ticker"] for s in approved)

    await send_hermes_alert(msg)
    return approved




async def monitor_active_signals():
    signals_result = supabase.table("signals")\
        .select("ticker")\
        .eq("status", "active")\
        .execute()

    active_tickers = [s["ticker"] for s in (signals_result.data or [])]
    if not active_tickers:
        return

    filings_result = supabase.table("filings")\
        .select("*")\
        .in_("impact", ["high", "medium"])\
        .eq("alert_sent", False)\
        .eq("sentiment", "negative")\
        .execute()

    for filing in (filings_result.data or []):
        ticker = filing.get("ticker")
        if ticker and ticker in active_tickers:
            await send_hermes_alert(
                f"⚠️ Active Signal Risk\n\n"
                f"Negative filing affects active signal: {ticker}\n\n"
                f"{filing.get('summary', '')}\n"
                f"Type: {filing.get('filing_type', '')}\n\n"
                f"Consider alerting subscribers."
            )
            supabase.table("filings")\
                .update({"alert_sent": True})\
                .eq("id", filing["id"])\
                .execute()

async def weekly_digest():
    """Friday performance digest — no AI, just numbers."""
    since = (date.today() - timedelta(days=7)).isoformat()

    result = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .gte("week_start", since)\
        .execute()

    records = result.data or []
    if not records:
        await send_hermes_alert("No closed signals this week.")
        return

    wins = [r for r in records if r["outcome"] == "tp1_hit"]
    losses = [r for r in records if r["outcome"] == "stopped_out"]
    win_rate = round(len(wins) / len(records) * 100) if records else 0
    avg_gain = round(
        sum(r.get("gain_percentage", 0) for r in records) / len(records), 2
    ) if records else 0

    win_lines = "\n".join([f"✅ {r['ticker']}: +{r.get('gain_percentage', 0):.2f}%" for r in wins])
    loss_lines = "\n".join([f"❌ {r['ticker']}: {r.get('gain_percentage', 0):.2f}%" for r in losses])

    msg = (
        f"Weekly Performance Digest\n\n"
        f"Signals closed: {len(records)}\n"
        f"Wins: {len(wins)} | Losses: {len(losses)}\n"
        f"Win rate: {win_rate}%\n"
        f"Average return: {avg_gain}%\n\n"
        f"Winners:\n{win_lines or 'None'}\n\n"
        f"Losers:\n{loss_lines or 'None'}"
    )

    await send_hermes_alert(msg)