import logging
import httpx
import anthropic
from app.config import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
from app.database import supabase
from app.scrapers.filings import get_all_filings
from datetime import datetime, UTC
logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

NGX_TICKERS = [
    "GTCO", "ZENITHBANK", "ACCESSCORP", "UBA", "FIDELITYBK", "FCMB",
    "WEMABANK", "STANBIC", "FIRSTHOLDCO", "JAIZBANK", "MTNN", "AIRTELAFRI",
    "SEPLAT", "OANDO", "TOTAL", "ETERNA", "CONOIL", "ARADEL",
    "DANGSUGAR", "NASCON", "NESTLE", "UNILEVER", "CADBURY", "NB",
    "GUINNESS", "HONYFLOUR", "BUAFOODS", "DANGCEM", "BUACEMENT", "WAPCO",
    "AIICO", "MANSARD", "CUSTODIAN", "NEM", "NGXGROUP", "TRANSCORP",
    "OKOMUOIL", "PRESCO", "JBERGER", "JULIUS", "NAHCO", "GEREGU"
]

def already_stored(filing_text: str) -> bool:
    result = supabase.table("filings")\
        .select("id")\
        .eq("filing_text", filing_text[:200])\
        .execute()
    return len(result.data) > 0

def classify_filing_type(text: str) -> str:
    text_upper = text.upper()
    if any(w in text_upper for w in ["EARNINGS", "FINANCIAL RESULT", "PROFIT", "REVENUE", "TURNOVER"]):
        return "earnings"
    if any(w in text_upper for w in ["DIVIDEND", "BONUS", "QUALIFICATION DATE"]):
        return "dividend"
    if any(w in text_upper for w in ["BOARD MEETING", "DIRECTOR", "APPOINTMENT", "RESIGNATION"]):
        return "board"
    if any(w in text_upper for w in ["ACQUISITION", "MERGER", "TAKEOVER", "STAKE"]):
        return "merger"
    if any(w in text_upper for w in ["AGM", "ANNUAL GENERAL", "EXTRAORDINARY GENERAL"]):
        return "agm"
    if any(w in text_upper for w in ["RIGHTS ISSUE", "PUBLIC OFFER", "CAPITAL RAISE"]):
        return "capital"
    return "general"

def analyze_filing(filing_text: str, ticker: str = None) -> dict:
    try:
        prompt = f"""Analyze this NGX company filing. Return ONLY a JSON object, no other text, no markdown, no backticks.

Filing: {filing_text[:300]}
{'Ticker: ' + ticker if ticker else ''}

Return exactly this JSON structure:
{{"ticker": "{ticker or 'null'}", "sentiment": "positive", "impact": "low", "summary": "one sentence summary", "action": "watch"}}

Rules:
- sentiment: positive, negative, or neutral only
- impact: high, medium, or low only  
- high impact: earnings, dividends, acquisitions, CEO changes, profit warnings
- medium impact: board meetings, AGM notices, minor corporate actions
- low impact: routine administrative filings
- action: buy, sell, hold, or watch only
- Return ONLY the JSON object, absolutely nothing else"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        
        # clean any markdown if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        
        import json
        return json.loads(raw)
        
    except Exception as e:
        logger.error(f"Filing analysis error: {e}")
        return {
            "ticker": ticker,
            "sentiment": "neutral",
            "impact": "low",
            "summary": filing_text[:100],
            "action": "watch"
        }

async def send_filing_alert(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient() as http:
            await http.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
    except Exception as e:
        logger.error(f"Filing alert send error: {e}")

async def run_filings_monitor():
    """Monitor NGX filings every 15 minutes during market hours"""
    logger.info("Running NGX filings monitor...")
    
    filings = await get_all_filings()
    if not filings:
        logger.info("No filings retrieved")
        return

    high_impact = []

    for filing in filings:
        text = filing["text"]
        
        if already_stored(text):
            continue

        filing_type = classify_filing_type(text)
        analysis = analyze_filing(text, filing.get("ticker"))

        # store in database
        supabase.table("filings").insert({
            "ticker": analysis.get("ticker") or filing.get("ticker"),
            "filing_text": text[:500],
            "filing_type": filing_type,
            "impact": analysis.get("impact", "low"),
            "sentiment": analysis.get("sentiment", "neutral"),
            "summary": analysis.get("summary", ""),
            "source": filing.get("source", "NGX"),
            "scraped_at": datetime.now(UTC).isoformat()
        }).execute()

        if analysis.get("impact") in ["high", "medium"]:
            high_impact.append({**filing, **analysis, "filing_type": filing_type})

    logger.info(f"Found {len(high_impact)} high/medium impact filings")

    if high_impact:
        await broadcast_filing_alerts(high_impact)

async def broadcast_filing_alerts(filings: list):
    from app.broadcaster import get_active_paid_users

    paid_users = get_active_paid_users(["basic", "pro"])
    if not paid_users:
        return

    for filing in filings:
        ticker = filing.get("ticker", "")
        sentiment = filing.get("sentiment", "neutral")
        summary = filing.get("summary", "")
        action = filing.get("action", "watch")
        filing_type = filing.get("filing_type", "general")
        source = filing.get("source", "NGX")

        emoji = "📈" if sentiment == "positive" else "📉" if sentiment == "negative" else "📋"
        impact_label = "🔴 High Impact" if filing.get("impact") == "high" else "🟡 Market Update"

        msg = (
            f"{emoji} {impact_label}\n\n"
            f"{'$' + ticker + ' — ' if ticker else ''}{filing_type.upper()}\n\n"
            f"{summary}\n\n"
            f"Recommendation: {action.upper()}\n"
            f"Source: {source}"
        )

        for user in paid_users:
            await send_filing_alert(user["telegram_id"], msg)

        # mark as sent
        supabase.table("filings")\
            .update({"alert_sent": True})\
            .eq("filing_text", filing["text"][:200])\
            .execute()

async def get_recent_filings_for_hermes() -> list:
    """Get recent high-impact filings for Hermes to use in signal review"""
    result = supabase.table("filings")\
        .select("ticker, filing_type, sentiment, impact, summary")\
        .in_("impact", ["high", "medium"])\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()
    return result.data or []