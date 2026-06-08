import httpx
from bs4 import BeautifulSoup
import logging
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

async def get_ngx_filings() -> list:
    """Scrape NGX company filings from abokiforex disclosures page"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://abokiforex.app/ngx-stocks/disclosures",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
                follow_redirects=True
            )
            
        soup = BeautifulSoup(response.text, "html.parser")
        filings = []
        
        # parse filing entries
        entries = soup.find_all(["div", "tr", "li"], class_=lambda x: x and any(
            word in str(x).lower() for word in ["disclosure", "filing", "announcement"]
        ))
        
        if not entries:
            # fallback — parse table rows or list items
            entries = soup.find_all("tr")[1:]  # skip header
        
        for entry in entries[:50]:
            text = entry.get_text(separator=" ", strip=True)
            if len(text) < 20:
                continue
                
            # extract ticker if present
            ticker = None
            words = text.split()
            for word in words:
                if word.isupper() and 2 <= len(word) <= 12:
                    ticker = word
                    break
            
            filings.append({
                "text": text[:500],
                "ticker": ticker,
                "source": "NGX Disclosures",
                "scraped_at": datetime.now(UTC).isoformat()
            })
        
        logger.info(f"Got {len(filings)} filings from NGX Disclosures")
        return filings
        
    except Exception as e:
        logger.error(f"Filings scrape error: {e}")
        return []

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