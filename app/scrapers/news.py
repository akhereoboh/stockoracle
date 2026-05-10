import httpx
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

NEWS_SOURCES = [
    {
        "name": "BusinessDay",
        "url": "https://businessday.ng/feed/",
        "type": "rss"
    },
    {
        "name": "Nairametrics", 
        "url": "https://nairametrics.com/feed/",
        "type": "rss"
    },
    {
        "name": "Stockswatch",
        "url": "https://stocksng.com/feed/",
        "type": "rss"
    }
]

def scrape_rss(url: str, source_name: str) -> list:
    try:
        response = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "xml")
        items = soup.find_all("item")[:15]
        results = []
        for item in items:
            title = item.find("title")
            link = item.find("link")
            desc = item.find("description")
            if title:
                results.append({
                    "headline": title.text.strip(),
                    "url": link.text.strip() if link else "",
                    "description": desc.text.strip()[:300] if desc else "",
                    "source": source_name
                })
        return results
    except Exception as e:
        logger.error(f"RSS scrape error {source_name}: {e}")
        return []

def scrape_html(url: str, source_name: str) -> list:
    try:
        response = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")[:15]
        results = []
        for article in articles:
            title = article.find(["h2", "h3"])
            link = article.find("a")
            if title:
                results.append({
                    "headline": title.text.strip(),
                    "url": link.get("href", "") if link else "",
                    "description": "",
                    "source": source_name
                })
        return results
    except Exception as e:
        logger.error(f"HTML scrape error {source_name}: {e}")
        return []

def get_all_news() -> list:
    all_news = []
    for source in NEWS_SOURCES:
        if source["type"] == "rss":
            news = scrape_rss(source["url"], source["name"])
        else:
            news = scrape_html(source["url"], source["name"])
        all_news.extend(news)
        logger.info(f"Got {len(news)} articles from {source['name']}")
    return all_news