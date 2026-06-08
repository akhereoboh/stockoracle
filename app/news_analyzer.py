import logging
import httpx
import anthropic
import json
from app.config import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
from app.database import supabase
from app.scrapers.filings import get_all_filings
from datetime import datetime, UTC, date

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# only these filing types matter to retail investors
ACTIONABLE_TYPES = [
    "Financial Statements",
    "Financial Results",
    "EarningForcast"
]

# corporate actions only matter if they contain these keywords
DIVIDEND_KEYWORDS = ["DIVIDEND", "QUALIFICATION DATE", "DISTRIBUTION"]
EARNINGS_KEYWORDS = ["PROFIT", "LOSS", "EARNINGS", "REVENUE", "RESULTS", "PAT", "TURNOVER"]
RISK_KEYWORDS = ["PROFIT WARNING", "GOING CONCERN", "INSOLVENCY", "DELISTING", "FRAUD", "INVESTIGATION"]

def is_actionable(filing_type: str, title: str) -> tuple[bool, str]:
    """
    Returns (should_process, reason).
    Only process filings that retail investors can act on.
    """
    title_upper = title.upper()

    if filing_type in ACTIONABLE_TYPES:
        return True, "financial_result"

    if filing_type == "Corporate Actions":
        if any(kw in title_upper for kw in DIVIDEND_KEYWORDS):
            return True, "dividend"
        if any(kw in title_upper for kw in EARNINGS_KEYWORDS):
            return True, "earnings"
        if any(kw in title_upper for kw in RISK_KEYWORDS):
            return True, "risk"

    return False, "skip"

def already_stored(ticker: str, title: str) -> bool:
    try:
        result = supabase.table("filings")\
            .select("id")\
            .eq("ticker", ticker)\
            .ilike("filing_text", f"%{title[:80]}%")\
            .execute()
        return len(result.data) > 0
    except:
        return False

def analyze_filing(filing_text: str, ticker: str, reason: str) -> dict:
    try:
        prompt = f"""Analyze this NGX company filing for retail investors. Return ONLY JSON.

Filing: {filing_text[:400]}
Ticker: {ticker}

Return exactly:
{{"sentiment": "positive/negative/neutral", "impact": "high/medium/low", "summary": "one clear sentence what this means for the stock price", "action": "buy/sell/hold/watch"}}

Impact rules:
- high: earnings beat/miss, profit warning, dividend declared, major acquisition
- medium: moderate earnings, minor corporate action
- low: routine update

Return ONLY the JSON, nothing else."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        return json.loads(raw.strip())

    except Exception as e:
        logger.error(f"Filing analysis error: {e}")
        return {
            "sentiment": "neutral",
            "impact": "low",
            "summary": filing_text[:100],
            "action": "watch"
        }

async def send_alert(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient() as http:
            await http.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
    except Exception as e:
        logger.error(f"Alert send error: {e}")

async def run_filings_monitor():
    logger.info("Running NGX filings monitor...")
    today = date.today().strftime("%-d %b %Y")  # e.g. "8 Jun 2026"

    filings = await get_all_filings()
    if not filings:
        logger.info("No filings retrieved")
        return

    todays_filings = [f for f in filings if f.get("date", "") == today]
    logger.info(f"Today's filings: {len(todays_filings)}")

    if not todays_filings:
        logger.info("No new filings today")
        return

    # get active signal tickers for risk alerts
    signals_result = supabase.table("signals")\
        .select("ticker")\
        .eq("status", "active")\
        .execute()
    active_tickers = [s["ticker"] for s in (signals_result.data or [])]

    earnings_alerts = []    # strong earnings → buy opportunity
    risk_alerts = []        # bad news on active signals → warn users
    dividend_alerts = []    # dividend declarations → plan entry

    for filing in todays_filings:
        ticker = filing.get("ticker", "")
        filing_type = filing.get("filing_type", "")
        title = filing.get("title", "")
        text = filing["text"]

        # check if worth processing
        should_process, reason = is_actionable(filing_type, title)
        if not should_process:
            continue

        # skip if already stored
        if already_stored(ticker, title):
            continue

        # analyze with Claude
        analysis = analyze_filing(text, ticker, reason)
        sentiment = analysis.get("sentiment", "neutral")
        impact = analysis.get("impact", "low")
        summary = analysis.get("summary", "")
        action = analysis.get("action", "watch")

        # store in database
        supabase.table("filings").insert({
            "ticker": ticker,
            "filing_text": text[:500],
            "filing_type": filing_type,
            "impact": impact,
            "sentiment": sentiment,
            "summary": summary,
            "source": filing.get("source", "NGX"),
            "scraped_at": datetime.now(UTC).isoformat()
        }).execute()

        # scenario 1: strong earnings — alert all paid users
        if reason == "financial_result" and sentiment == "positive" and impact == "high":
            earnings_alerts.append({
                "ticker": ticker,
                "summary": summary,
                "action": action
            })

        # scenario 2: bad news on active signal — warn users holding it
        if sentiment == "negative" and impact in ["high", "medium"] and ticker in active_tickers:
            risk_alerts.append({
                "ticker": ticker,
                "summary": summary
            })

        # scenario 3: dividend announced — inform all paid users
        if reason == "dividend" and impact in ["high", "medium"]:
            dividend_alerts.append({
                "ticker": ticker,
                "summary": summary
            })

    logger.info(
        f"Earnings alerts: {len(earnings_alerts)} | "
        f"Risk alerts: {len(risk_alerts)} | "
        f"Dividend alerts: {len(dividend_alerts)}"
    )

    if earnings_alerts or risk_alerts or dividend_alerts:
        await broadcast_alerts(earnings_alerts, risk_alerts, dividend_alerts)

async def broadcast_alerts(earnings: list, risks: list, dividends: list):
    from app.broadcaster import get_active_paid_users
    paid_users = get_active_paid_users(["basic", "pro"])
    if not paid_users:
        return

    # earnings alerts — buying opportunity
    for alert in earnings:
        msg = (
            f"📈 Earnings Alert\n\n"
            f"${alert['ticker']}\n\n"
            f"{alert['summary']}\n\n"
            f"Action: {alert['action'].upper()}"
        )
        for user in paid_users:
            await send_alert(user["telegram_id"], msg)

    # risk alerts — only send to users with that active signal
    for alert in risks:
        msg = (
            f"⚠️ Signal Risk Alert\n\n"
            f"${alert['ticker']} — Negative News\n\n"
            f"{alert['summary']}\n\n"
            f"Review your position and consider tightening your stop loss."
        )
        for user in paid_users:
            await send_alert(user["telegram_id"], msg)

    # dividend alerts — planning opportunity
    for alert in dividends:
        msg = (
            f"💰 Dividend Alert\n\n"
            f"${alert['ticker']}\n\n"
            f"{alert['summary']}"
        )
        for user in paid_users:
            await send_alert(user["telegram_id"], msg)

async def get_recent_filings_for_hermes() -> list:
    """Fresh filings for Hermes signal review"""
    result = supabase.table("filings")\
        .select("ticker, filing_type, sentiment, impact, summary")\
        .in_("impact", ["high", "medium"])\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()
    return result.data or []