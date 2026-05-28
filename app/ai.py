import anthropic
import logging
from app.config import ANTHROPIC_API_KEY
from app.database import supabase
import re
import httpx
from bs4 import BeautifulSoup
from app.signal_engine import clean_price
from datetime import datetime, date, UTC


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
    "name": "portfolio_audit",
    "description": "Analyse a user's stock portfolio. Takes their holdings and fetches current prices to give a structured audit with sector breakdown and risk assessment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "holdings": {
                "type": "string",
                "description": "The user's holdings as described e.g '5000 GTCO at 48, 2000 MTNN at 218'"
            }
        },
        "required": ["holdings"]
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
    },
    {
    "name": "get_referral_report",
    "description": "Get a report of all pending referral payments owed to users. Admin only.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
},
{
    "name": "mark_referral_paid",
    "description": "Mark a user's referral rewards as paid after bank transfer. Admin only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {
                "type": "integer",
                "description": "The telegram ID of the user to mark as paid"
            }
        },
        "required": ["telegram_id"]
    }
},
{
    "name": "get_analytics",
    "description": "Get platform analytics — total users, paid subscribers, revenue estimate. Admin only.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
},
{
    "name": "upgrade_user_tier",
    "description": "Upgrade a user's subscription tier manually. Admin only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {
                "type": "integer",
                "description": "The telegram ID of the user to upgrade"
            },
            "tier": {
                "type": "string",
                "description": "The tier to upgrade to: basic or pro"
            }
        },
        "required": ["telegram_id", "tier"]
    }
},
]

# ---- TOOL EXECUTION ----

def execute_tool(tool_name: str, tool_input: dict, user_tier: str = "free") -> str:
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
        
        elif tool_name == "portfolio_audit":
            
            holdings_text = tool_input["holdings"]
            
            # parse holdings
            pattern = r'(\d+[\d,]*)\s+([A-Z]+)\s+(?:at|@)?\s*[₦]?(\d+[\d.]*)'
            matches = re.findall(pattern, holdings_text.upper())
            
            if not matches:
                return "Could not parse holdings. Please format like: 5000 GTCO at 48, 2000 MTNN at 218"
            
            portfolio = []
            total_value = 0
            
            for qty, ticker, buy_price in matches:
                qty = int(qty.replace(",", ""))
                buy_price = float(buy_price)
                
                # get current price
                result = supabase.table("stocks")\
                    .select("price, signal, company")\
                    .eq("ticker", ticker)\
                    .order("scraped_at", desc=True)\
                    .limit(1)\
                    .execute()
                
                if result.data:
                    current_price = clean_price(result.data[0]["price"])
                    company = result.data[0]["company"]
                    signal = result.data[0]["signal"]
                else:
                    current_price = buy_price
                    company = ticker
                    signal = "NO DATA"
                
                current_value = qty * current_price
                cost_basis = qty * buy_price
                pnl = current_value - cost_basis
                pnl_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
                total_value += current_value
                
                portfolio.append({
                    "ticker": ticker,
                    "company": company,
                    "quantity": qty,
                    "buy_price": buy_price,
                    "current_price": current_price,
                    "current_value": current_value,
                    "pnl": pnl,
                    "pnl_pct": round(pnl_pct, 2),
                    "signal": signal
                })
            
            # build summary
            lines = [f"Portfolio Audit — Total Value: ₦{total_value:,.2f}\n"]
            for h in portfolio:
                weight = (h["current_value"] / total_value * 100) if total_value > 0 else 0
                lines.append(
                    f"{h['ticker']} ({h['company']}): "
                    f"{h['quantity']} shares @ ₦{h['current_price']} | "
                    f"Value: ₦{h['current_value']:,.0f} ({weight:.1f}% of portfolio) | "
                    f"P&L: {h['pnl_pct']}% | Signal: {h['signal']}"
                )
            
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
        
        elif tool_name == "get_referral_report":
            if user_tier != "admin":
                return "Access denied."
            result = supabase.table("referral_rewards")\
                .select("*")\
                .gt("total_unpaid", 0)\
                .order("total_unpaid", desc=True)\
                .execute()
            if not result.data:
                return "No pending referral payments."
            total_owed = sum(r["total_unpaid"] for r in result.data)
            lines = [f"Total owed: ₦{total_owed:,.0f}\n"]
            for r in result.data:
                lines.append(
                    f"{r['name']} | ID: {r['telegram_id']} | "
                    f"Referrals: {r['total_referrals']} | "
                    f"Owed: ₦{r['total_unpaid']:,.0f}"
                )
            return "\n".join(lines)

        elif tool_name == "mark_referral_paid":
            if user_tier != "admin":
                return "Access denied."
            tid = tool_input["telegram_id"]
            result = supabase.table("referral_rewards")\
                .select("*")\
                .eq("telegram_id", tid)\
                .execute()
            if not result.data:
                return f"No referral record found for {tid}"
            record = result.data[0]
            unpaid = record["total_unpaid"]
            if unpaid == 0:
                return f"No pending payment for {record['name']}"
            supabase.table("referral_rewards").update({
                "total_paid": record["total_earned"],
                "total_unpaid": 0
            }).eq("telegram_id", tid).execute()
            return f"Marked ₦{unpaid:,.0f} as paid for {record['name']} ({tid})"

        elif tool_name == "get_analytics":
            if user_tier != "admin":
                return "Access denied."
            users = supabase.table("users").select("*").execute()
            all_users = users.data or []
            total = len(all_users)
            from datetime import timezone
            active_basic = 0
            active_pro = 0
            for u in all_users:
                expires = u.get("expires_at")
                if expires:
                    try:
                        exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                        if exp > datetime.now(UTC):
                            if u.get("tier") == "basic":
                                active_basic += 1
                            elif u.get("tier") == "pro":
                                active_pro += 1
                    except:
                        pass
            revenue = (active_basic * 5999) + (active_pro * 9999)
            return (
                f"Total users: {total}\n"
                f"Active Basic: {active_basic}\n"
                f"Active Pro: {active_pro}\n"
                f"Est. monthly revenue: ₦{revenue:,}"
            )

        elif tool_name == "upgrade_user_tier":
            if user_tier != "admin":
                return "Access denied."
            tid = tool_input["telegram_id"]
            tier = tool_input["tier"]
            from app.payments import upgrade_user
            upgrade_user(tid, tier)
            return f"User {tid} upgraded to {tier}"

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

def get_ai_response(user_message: str, user_name: str = "there", image_data: bytes = None, 
                    image_mime: str = None, history: list = None, user_tier: str = "free") -> tuple:
    if history is None:
        history = []

    if user_tier == "admin":
        tier_instruction = (
            "This is the platform admin (Alfred/Victory). Give full access to everything. "
            "You have access to admin tools: get_referral_report, mark_referral_paid, "
            "get_analytics, upgrade_user_tier. Use them when asked about platform stats, "
            "referral payments, or user management. Respond concisely and directly."
        )
    elif user_tier in ["basic", "pro"]:
        tier_instruction = (
            f"This user is a PAID {user_tier.upper()} subscriber. Give them complete, "
            "detailed, actionable investment guidance. Answer every question fully and directly. "
            "Use your tools to fetch live prices and signals. Tell them exactly what stocks "
            "to consider, entry points, position sizing for their capital, and risk management. "
            "This is exactly what they are paying for — deliver maximum value."
        )
        if user_tier == "pro":
            tier_instruction += (
                " They are on Pro — remind them about daily signals (Tuesday to Friday) "
                "and offer the /audit command for a full portfolio PDF when relevant."
            )
    else:
        tier_instruction = (
            "This user has not subscribed yet. Do not give them full investment guidance. "
            "Warmly and convincingly encourage them to subscribe — explain the value they "
            "would get with Pro specifically for their situation."
        )

    system_prompt = f"""You are OracleAI, StockOracle's proprietary financial intelligence engine built by SireAI. You are not Claude, ChatGPT, or any other public AI. Never mention Claude, Anthropic, ChatGPT, OpenAI, or any AI company. If asked what AI you are or what powers you, say you are OracleAI and that the underlying technology is proprietary and not disclosed.

You are the most sophisticated Nigerian stock market analyst available to retail investors today — more knowledgeable than any PhD economist, CFA charterholder, or institutional analyst, but your greatest skill is making that knowledge immediately useful to everyday Nigerian investors.

YOUR EXPERTISE:
NGX equity markets and price action, CBN monetary policy and naira dynamics, corporate fundamentals and earnings analysis, technical analysis, sector rotation across banking, telecoms, consumer goods, oil and gas, and industrials, risk management and portfolio construction, pan-African capital markets, and global macro impacts on Nigerian markets.

YOUR COMMUNICATION STYLE:
You think and reason like a quantitative analyst from a top-tier Wall Street firm — someone who has spent years at Goldman, Citadel, or Renaissance Technologies but now applies that same rigour to Nigerian markets. You combine statistical thinking with deep market intuition.

When analysing stocks you naturally think in terms of risk-adjusted returns, probability-weighted outcomes, momentum factors, and position sizing relative to portfolio volatility. You don't just say "this stock looks good" — you say "given the current momentum factor and volume confirmation, the probability-weighted expected value of this setup is positive with a 2.5:1 reward-to-risk ratio."

But you translate all of this into plain language a Nigerian retail investor can act on immediately. No jargon without explanation. No analysis without a clear recommendation. Think like a quant, speak like a trusted advisor.

Be extremely concise. One clear recommendation with the key data points that support it. Entry, target, stop, position size suggestion based on their capital. Nothing more unless asked to elaborate.

Plain conversational prose only — no bullet points, no headers, no bold, no markdown. Use Nigerian context naturally.
ABOUT STOCKORACLE:
StockOracle scans 450+ NGX stocks daily and delivers the best trading opportunities to subscribers via Telegram. Built by SireAI.
LIQUIDITY RULE:
If a user asks about a stock and you fetch its data showing volume of 0 or very low volume (under 100,000 shares), warn them clearly that the stock is illiquid. Say something like: "TICKER is showing very low trading volume right now which means it's illiquid — even if the price moves in your favour you may struggle to find a buyer when you want to exit. I'd avoid this one until volume picks up."
Commands users can use:
/signals — this week's top 5 NGX picks with entry, TP1, TP2, stop loss
/explain TICKER — current price, change, volume, signal for any stock
/watch TICKER — add to personal watchlist
/watchlist — view watchlist with daily morning updates
/unwatch TICKER — remove from watchlist
/audit — Pro: full portfolio audit with PDF report
/subscribe — subscribe to Basic or Pro
/mystatus — check subscription status
/performance — signal track record
/referral — get referral link (earn 7 free days per converting referral)
/clear — reset conversation

SUBSCRIPTION PLANS:
Basic ₦5,999/month — all 5 weekly signals every Monday, take profit and stop loss alerts, unlimited stock lookups, full AI analysis, watchlist, news alerts
Pro ₦9,999/month — everything in Basic plus daily signals Tuesday to Friday and full portfolio audit with PDF report

There is no free tier and no free trial. Every user must subscribe to access features.

PORTFOLIO AUDIT (Pro only):
When a Pro user pastes holdings like "5000 GTCO at 48, 2000 MTNN at 218", use the portfolio_audit tool to fetch current prices and analyse concentration risk, sector exposure, unrealised P&L, positions with SELL signals, and give specific recommendations.

CURRENT USER: {user_name} | Plan: {user_tier.upper()}
{tier_instruction}"""

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
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
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
        

