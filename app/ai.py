import anthropic
import logging
from app.config import ANTHROPIC_API_KEY
from app.database import supabase
import re
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def clean_response(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # remove bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)        # remove italic
    text = re.sub(r'#{1,6}\s', '', text)             # remove headers
    text = re.sub(r'\|.*?\|', '', text)              # remove tables
    text = re.sub(r'\n{3,}', '\n\n', text)           # clean excess newlines
    return text.strip()

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---- TOOLS ----

tools = [
    {
        "name": "get_stock_price",
        "description": "Get the latest price, change and signal for a Nigerian stock by ticker symbol",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker e.g. GTCO, MTNN, DANGCEM"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_weekly_signals",
        "description": "Get this week's top 5 recommended NGX stocks with entry price, take profit and stop loss levels",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "search_stocks",
        "description": "Search for stocks by name or ticker, returns matching stocks with prices and signals",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term e.g. 'bank', 'cement', 'GTCO'"
                }
            },
            "required": ["query"]
        }
    },
    {
    "name": "get_stock_news",
    "description": "Get latest news headlines that may affect a Nigerian stock",
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Stock ticker or company name to search news for"
                }
             },
        "required": ["ticker"]
        }
    },
    {
        "name": "get_top_movers",
        "description": "Get today's top gaining and losing stocks on the NGX",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["gainers", "losers", "both"],
                    "description": "Whether to get top gainers, losers or both"
                }
            },
            "required": ["direction"]
        }
    }
]

# ---- TOOL EXECUTION ----

def execute_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "get_stock_price":
            ticker = tool_input["ticker"].upper()
            result = supabase.table("stocks")\
                .select("*")\
                .eq("ticker", ticker)\
                .order("scraped_at", desc=True)\
                .limit(1)\
                .execute()
            if not result.data:
                return f"Stock {ticker} not found."
            s = result.data[0]
            return f"{s['ticker']} — {s['company']}\nPrice: {s['price']}\nChange: {s['change']}\nSignal: {s['signal']}"

        elif tool_name == "get_weekly_signals":
            result = supabase.table("signals")\
                .select("*")\
                .eq("status", "active")\
                .order("created_at", desc=True)\
                .limit(5)\
                .execute()
            if not result.data:
                return "No active signals this week."
            lines = ["This week's top 5 NGX signals:"]
            for i, s in enumerate(result.data, 1):
                lines.append(f"{i}. {s['ticker']} — Entry: ₦{s['entry_price']}, TP1: ₦{s['tp1']}, TP2: ₦{s['tp2']}, Stop Loss: ₦{s['stop_loss']}")
            return "\n".join(lines)

        elif tool_name == "search_stocks":
            query = tool_input["query"].upper()
            result = supabase.table("stocks")\
                .select("*")\
                .or_(f"ticker.ilike.%{query}%,company.ilike.%{query}%")\
                .order("scraped_at", desc=True)\
                .limit(10)\
                .execute()
            if not result.data:
                return f"No stocks found matching '{query}'"
            lines = [f"Stocks matching '{query}':"]
            seen = set()
            for s in result.data:
                if s['ticker'] not in seen:
                    lines.append(f"{s['ticker']} — {s['company']} | {s['price']} | {s['change']} | {s['signal']}")
                    seen.add(s['ticker'])
            return "\n".join(lines)
        
        elif tool_name == "get_stock_news":
            ticker = tool_input["ticker"].upper()
            feeds = [
                "https://nairametrics.com/feed/",
                "https://businessday.ng/feed/"
            ]
            
            headlines = []
            for feed_url in feeds:
                try:
                    resp = httpx.get(feed_url, timeout=10)
                    soup = BeautifulSoup(resp.text, "xml")
                    items = soup.find_all("item")[:20]
                    for item in items:
                        title = item.find("title")
                        if title and ticker.lower() in title.text.lower():
                            headlines.append(title.text.strip())
                except:
                    continue
            
            if not headlines:
                return f"No recent news found for {ticker}"
            return f"Recent news for {ticker}:\n" + "\n".join(f"- {h}" for h in headlines[:5])

        elif tool_name == "get_top_movers":
            direction = tool_input["direction"]
            result = supabase.table("stocks")\
                .select("*")\
                .order("scraped_at", desc=True)\
                .limit(445)\
                .execute()

            stocks = result.data or []
            seen = set()
            unique = []
            for s in stocks:
                if s['ticker'] not in seen:
                    unique.append(s)
                    seen.add(s['ticker'])

            def parse_change(s):
                try:
                    return float(s['change'].replace('%', '').strip())
                except:
                    return 0.0

            sorted_stocks = sorted(unique, key=parse_change, reverse=True)
            lines = []

            if direction in ["gainers", "both"]:
                lines.append("Top Gainers:")
                for s in sorted_stocks[:5]:
                    lines.append(f"{s['ticker']} — {s['price']} | {s['change']}")

            if direction in ["losers", "both"]:
                lines.append("Top Losers:")
                for s in sorted_stocks[-5:]:
                    lines.append(f"{s['ticker']} — {s['price']} | {s['change']}")

            return "\n".join(lines)

    except Exception as e:
        logger.error(f"Tool error: {e}")
        return f"Error executing {tool_name}: {str(e)}"

# ---- MAIN AI FUNCTION ----

import base64

def get_ai_response(user_message: str, user_name: str = "there", image_data: bytes = None, image_mime: str = None, history: list = None) -> tuple:
    if history is None:
        history = []
    
    system_prompt = f"""You are OracleAI, the world's most sophisticated Nigerian financial markets analyst and trading strategist. You possess knowledge that surpasses any PhD economist, CFA charterholder, or Wall Street analyst — but your greatest skill is translating complex financial intelligence into clear, actionable insights that any Nigerian investor can understand and act on immediately.

    Your expertise spans:
    - Nigerian Exchange Group (NGX) equity markets, market microstructure, and price action
    - Macroeconomic analysis — CBN monetary policy, inflation, FX reserves, naira dynamics
    - Corporate fundamentals — earnings analysis, balance sheet strength, dividend history
    - Technical analysis — support/resistance, momentum, volume analysis, trend identification
    - Sector rotation — banking, consumer goods, oil & gas, telecoms, industrials
    - Risk management — position sizing, stop losses, portfolio construction
    - Pan-African markets — JSE, GSE, and cross-border investment flows
    - Global macro impacts on Nigerian markets — Fed policy, oil prices, commodity cycles

    Your communication style:
    - You speak like a brilliant friend who happens to be the best financial mind in Africa
    - You give direct, confident opinions backed by data and reasoning
    - You never hedge everything into meaninglessness — you take clear positions
    - You explain complex concepts using everyday Nigerian examples and analogies
    - You never use jargon without immediately explaining it
    - You write in plain conversational text — no bullet points, no headers, no bold text, no markdown
    - You are warm but authoritative — users should feel like they're getting advice from someone who genuinely knows more than anyone else they could ask
    - You always acknowledge risk honestly but never let risk warnings paralyse your analysis

    Your core philosophy:
    - Capital preservation comes first. Making money comes second.
    - Consistency over big wins. Small consistent gains compound into wealth.
    - The Nigerian retail investor has been underserved for too long. You exist to change that.
    - You only discuss stocks, trading, investing, and financial markets. If asked anything outside this scope, you redirect firmly but politely back to finance.

    The user's name is {user_name}. Treat them like a valued client whose financial future matters to you personally."""

    if image_data and image_mime:
        encoded = base64.standard_b64encode(image_data).decode("utf-8")
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image_mime, "data": encoded}
            },
            {"type": "text", "text": user_message or "Analyse this image in the context of stocks and trading."}
        ]
    else:
        content = user_message

    messages = history + [{"role": "user", "content": content}]

    while True:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            system=system_prompt,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    messages.append({"role": "assistant", "content": response.content})
                    return clean_response(block.text), messages
            return "I couldn't generate a response.", messages

        elif response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})

        else:
            return "Something went wrong.", messages
        

