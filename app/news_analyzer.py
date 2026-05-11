import logging
import anthropic
from app.config import ANTHROPIC_API_KEY
from app.database import supabase
from app.scrapers.news import get_all_news
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

def already_stored(headline: str) -> bool:
    result = supabase.table("news_alerts")\
        .select("id")\
        .eq("headline", headline[:200])\
        .execute()
    return len(result.data) > 0

def analyze_headline(headline: str, description: str) -> dict:
    try:
        prompt = f"""Analyze this Nigerian financial news headline and description.

Headline: {headline}
Description: {description}

Respond ONLY with a JSON object like this:
{{
    "tickers": ["GTCO", "MTNN"],
    "sentiment": "positive",
    "impact": "high",
    "summary": "One sentence plain English explanation of what this means for investors",
    "action": "What investors should consider doing"
}}

Rules:
- tickers: list of NGX ticker symbols affected. Only use real NGX tickers. Empty array if none.
- sentiment: "positive", "negative", or "neutral"
- impact: "high", "medium", or "low"
- high impact means: CBN policy changes, major earnings surprises, large investments, mergers, sanctions
- medium impact means: regular earnings, management changes, product launches
- low impact means: minor news, general market commentary
- If no specific NGX stock is affected, return empty tickers array and impact "low"

Only return the JSON, nothing else."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        text = response.content[0].text.strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return {"tickers": [], "sentiment": "neutral", "impact": "low", "summary": "", "action": ""}

async def run_news_monitor():
    logger.info("Running news monitor...")
    articles = get_all_news()
    high_impact = []

    for article in articles:
        headline = article["headline"]
        if already_stored(headline):
            continue

        analysis = analyze_headline(headline, article.get("description", ""))

        supabase.table("news_alerts").insert({
            "headline": headline[:200],
            "tickers": analysis.get("tickers", []),
            "sentiment": analysis.get("sentiment", "neutral"),
            "impact": analysis.get("impact", "low"),
            "source": article["source"],
            "url": article.get("url", ""),
            "created_at": datetime.now(UTC).isoformat()
        }).execute()

        if analysis.get("impact") == "high" and analysis.get("tickers"):
            high_impact.append({**article, **analysis})

    logger.info(f"Found {len(high_impact)} high impact stories")

    if high_impact:
        await send_news_alerts(high_impact)

async def send_news_alerts(stories: list):
    from app.broadcaster import get_active_paid_users, _send
    paid_users = get_active_paid_users(["basic", "pro"])

    for story in stories:
        tickers = story.get("tickers", [])
        sentiment = story.get("sentiment", "neutral")
        summary = story.get("summary", "")
        action = story.get("action", "")
        headline = story.get("headline", "")
        source = story.get("source", "")
        url = story.get("url", "")

        emoji = "📈" if sentiment == "positive" else "📉" if sentiment == "negative" else "📰"

        msg = (
            f"{emoji} Market Alert\n\n"
            f"{headline}\n\n"
            f"What this means: {summary}\n\n"
            f"Stocks affected: {', '.join(tickers)}\n\n"
            f"What to consider: {action}\n\n"
            f"Source: {source}"
        )
        if url:
            msg += f"\n{url}"

        for user in paid_users:
            await _send(user["telegram_id"], msg)

        supabase.table("news_alerts")\
            .update({"alert_sent": True})\
            .eq("headline", headline[:200])\
            .execute()