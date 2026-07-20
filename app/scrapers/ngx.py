from playwright.async_api import async_playwright
import re

NGX_URL = "https://abokiforex.app/ngx-stocks"

async def get_ngx_prices() -> list:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(NGX_URL, timeout=60000)
        
        # wait for initial load
        await page.wait_for_timeout(5000)
        
        # scroll to bottom repeatedly to trigger lazy loading
        prev_height = 0
        for _ in range(20):
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            prev_height = curr_height
        
        # scroll back to top and wait for any final renders
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(3000)
        
        content = await page.inner_text("body")
        await browser.close()
        
        results = []
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r'^[A-Z][A-Z0-9]{1,14}$', line) and i + 1 < len(lines):
                ticker = line
                company = lines[i+1] if i+1 < len(lines) else ""
                signal = ""
                price = ""
                change = ""
                volume = "0"
                for j in range(i+1, min(i+10, len(lines))):
                    if "BUY" in lines[j] or "SELL" in lines[j] or "HOLD" in lines[j] or "NO DATA" in lines[j]:
                        signal = lines[j]
                    if lines[j].startswith("₦") and not lines[j].startswith("₦0.00"):
                        price = lines[j]
                    if re.match(r'^[+-]\d+\.\d+%$', lines[j]):
                        change = lines[j]
                    if lines[j] == "Volume" and j+1 < len(lines):
                        raw_vol = lines[j+1].replace(",", "").strip()
                        if raw_vol.isdigit():
                            volume = raw_vol
                if price:
                    results.append({
                        "ticker": ticker,
                        "company": company,
                        "price": price,
                        "change": change,
                        "signal": signal,
                        "volume": volume
                    })
                    i += 8
                    continue
            i += 1
        
        return results