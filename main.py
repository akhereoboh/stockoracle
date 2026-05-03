import asyncio
from app.scrapers.ngx import get_ngx_prices
from app.database import supabase
from datetime import datetime

async def save_stocks():
    print("Scraping NGX stocks...")
    stocks = await get_ngx_prices()
    print(f"Found {len(stocks)} stocks, saving to Supabase...")
    
    for stock in stocks:
        stock["scraped_at"] = datetime.utcnow().isoformat()
    
    result = supabase.table("stocks").insert(stocks).execute()
    print(f"Saved successfully")

asyncio.run(save_stocks())