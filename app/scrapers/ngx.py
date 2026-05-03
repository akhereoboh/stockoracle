from playwright.async_api import async_playwright
import re

NGX_URL = "https://abokiforex.app/ngx-stocks"

async def get_ngx_prices() -> list:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(NGX_URL, timeout=60000)
        await page.wait_for_timeout(8000)
        
        content = await page.inner_text("body")
        await browser.close()
        
        results = []
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            # ticker is a short uppercase word
            if re.match(r'^[A-Z0-9]{2,15}$', line) and i + 1 < len(lines):
                ticker = line
                company = lines[i+1] if i+1 < len(lines) else ""
                signal = ""
                price = ""
                change = ""
                
                # look ahead for price, signal, change
                for j in range(i+1, min(i+6, len(lines))):
                    if "BUY" in lines[j] or "SELL" in lines[j] or "HOLD" in lines[j] or "NO DATA" in lines[j]:
                        signal = lines[j]
                    if lines[j].startswith("₦") and not lines[j].startswith("₦0.00"):
                        price = lines[j]
                    if re.match(r'^[+-]\d+\.\d+%$', lines[j]):
                        change = lines[j]
                
                if price:
                    results.append({
                        "ticker": ticker,
                        "company": company,
                        "price": price,
                        "change": change,
                        "signal": signal
                    })
                i += 1
            else:
                i += 1
        
        return results