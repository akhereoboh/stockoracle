import anthropic
import logging
from app.config import ANTHROPIC_API_KEY
from app.database import supabase

logger = logging.getLogger(__name__)

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

def get_ai_response(user_message: str, user_name: str = "there", image_data: bytes = None, image_mime: str = None) -> str:
    system_prompt = f"""You are StockOracle AI, a helpful Nigerian stock market assistant built by SireAI.

You help Nigerian retail investors understand the stock market, find good stocks to trade, and make informed decisions.

Your personality:
- Friendly and clear, like a knowledgeable friend explaining stocks
- Always use Nigerian context (naira prices, NGX exchange, Nigerian companies)
- Never guarantee profits — always remind users to manage risk
- Be concise but thorough

You have tools to fetch real live NGX stock data. Always use them when users ask about specific stocks, signals, or market movers.

STRICT RULE: You only discuss topics related to stocks, trading, investing, and financial markets. If a user sends an image or message unrelated to stocks or finance, politely decline and redirect them.

The user's name is {user_name}."""

    # build message content
    if image_data and image_mime:
        encoded = base64.standard_b64encode(image_data).decode("utf-8")
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime,
                    "data": encoded
                }
            },
            {
                "type": "text",
                "text": user_message or "Please analyse this image in the context of stocks and trading."
            }
        ]
    else:
        content = user_message

    messages = [{"role": "user", "content": content}]

    # agentic loop
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
                    return block.text
            return "I couldn't generate a response. Please try again."

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
            return "Something went wrong. Please try again."