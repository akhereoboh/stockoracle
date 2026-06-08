import httpx
from bs4 import BeautifulSoup
import logging
from datetime import datetime, UTC

logger = logging.getLogger(__name__)



async def get_ngx_filings() -> list:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://abokiforex.app/ngx-stocks/disclosures",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
                follow_redirects=True
            )

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.find_all("div", class_="disclosure-card")
        
        filings = []
        for card in cards[:50]:  # limit to 50 most recent
            ticker = card.get("data-symbol", "").strip()
            filing_type = card.get("data-type", "").strip()
            
            # skip bonds and NGX notices
            if ticker in ["NGX"] or not ticker:
                continue
            
            title_div = card.find("div", class_="card-title")
            summary_div = card.find("div", class_="card-summary")
            date_span = card.find("span", class_="card-date")
            
            title = title_div.get_text(strip=True) if title_div else ""
            summary = summary_div.get_text(separator=" ", strip=True) if summary_div else ""
            date = date_span.get_text(strip=True) if date_span else ""
            
            if not summary:
                continue
            
            filings.append({
                "ticker": ticker,
                "filing_type": filing_type,
                "title": title,
                "text": f"{title}. {summary}"[:500],
                "date": date,
                "source": "NGX Disclosures",
                "scraped_at": datetime.now(UTC).isoformat()
            })

        logger.info(f"Got {len(filings)} filings from NGX Disclosures")
        return filings

    except Exception as e:
        logger.error(f"Filings scrape error: {e}")
        return []

async def get_all_filings() -> list:
    return await get_ngx_filings()

async def get_ngxpulse_filings() -> list:
    """Scrape NGX Pulse filings as backup source"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://ngxpulse.ng/filings",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
                follow_redirects=True
            )
        
        soup = BeautifulSoup(response.text, "html.parser")
        filings = []
        
        # find filing entries
        articles = soup.find_all(["article", "div", "li"])
        
        for article in articles[:30]:
            text = article.get_text(separator=" ", strip=True)
            if len(text) < 30 or len(text) > 1000:
                continue
            
            # look for company ticker pattern
            ticker = None
            import re
            tickers = re.findall(r'\b[A-Z]{2,12}\b', text)
            if tickers:
                ticker = tickers[0]
            
            filings.append({
                "text": text[:500],
                "ticker": ticker,
                "source": "NGX Pulse",
                "scraped_at": datetime.now(UTC).isoformat()
            })
        
        logger.info(f"Got {len(filings)} filings from NGX Pulse")
        return filings
        
    except Exception as e:
        logger.error(f"NGX Pulse scrape error: {e}")
        return []

async def get_all_filings() -> list:
    primary = await get_ngx_filings()
    if len(primary) > 5:
        return primary
    # fallback to NGX Pulse
    backup = await get_ngxpulse_filings()
    return primary + backup