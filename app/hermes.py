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

    # get FRESH regulatory filings instead of stale news
    filings = await get_recent_filings_for_hermes()

    # get market breadth
    stocks_result = supabase.table("stocks")\
        .select("change")\
        .eq("trade_date", date.today().isoformat())\
        .execute()
    stocks = stocks_result.data or []
    if stocks:
        up = sum(1 for s in stocks if s.get("change", "").startswith("+"))
        breadth = up / len(stocks) * 100
    else:
        breadth = 50

    signals_text = "\n".join([
        f"{s['ticker']} — Entry: ₦{s['entry_price']}, TP1: ₦{s['tp1']}, SL: ₦{s['stop_loss']}"
        for s in signals
    ])

    if filings:
        filings_text = "\n".join([
            f"{f.get('ticker','?')} — {f.get('filing_type','').upper()}: {f.get('summary','')} "
            f"(Sentiment: {f.get('sentiment','neutral')}, Impact: {f.get('impact','low')})"
            for f in filings
        ])
    else:
        filings_text = "No material filings in the last 24 hours"

    prompt = f"""You are Hermes, signal quality auditor for StockOracle.

Review these signals before they broadcast to paying users. Real money is at stake. Be strict.

PROPOSED SIGNALS:
{signals_text}

MARKET BREADTH: {breadth:.1f}% of NGX stocks are up today

RECENT NGX REGULATORY FILINGS (fresh — not news articles):
{filings_text}

For each signal decide APPROVE or REJECT:
- Reject if a recent filing shows negative earnings, profit warning, or regulatory issues for that stock
- Reject if the stock's sector has negative material filings
- Reject if market breadth is below 40%
- Approve if fundamentals are clean and breadth supports it

Format:
TICKER: APPROVE/REJECT — reason
...
APPROVED: TICKER1, TICKER2"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )

        review = response.content[0].text
        logger.info(f"Hermes review:\n{review}")

        approved_tickers = []
        for line in review.split("\n"):
            if line.strip().startswith("APPROVED:"):
                tickers_str = line.replace("APPROVED:", "").strip()
                approved_tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
                break

        approved = [s for s in signals if s["ticker"] in approved_tickers]
        rejected = [s["ticker"] for s in signals if s["ticker"] not in approved_tickers]

        msg = (
            f"Signal Audit Complete\n\n"
            f"Proposed: {len(signals)} | Approved: {len(approved)} | Rejected: {len(rejected)}\n"
            f"Market breadth: {breadth:.1f}%\n\n"
            f"{review}"
        )
        await send_hermes_alert(msg)
        return approved

    except Exception as e:
        logger.error(f"Hermes review failed: {e}")
        await send_hermes_alert(f"Review failed: {e}\nFalling back to all signals.")
        return signals

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