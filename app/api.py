
from fastapi import FastAPI, Request, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import supabase
from app.signal_engine import (
    is_tradeable_equity, clean_price, clean_volume, clean_change,
    check_market_breadth, get_latest_stocks, get_all_history_bulk
)
from app.technical import full_technical_analysis, interpret_analysis
from datetime import datetime, UTC, date, timedelta
from typing import Optional
import logging
import jwt
import os

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("JWT_SECRET", "stockoracle_secret_2026")
ALGORITHM = "HS256"

api_app = FastAPI(
    title="StockNX API",
    version="1.0.0",
    description="NGX market intelligence API for StockNX Flutter app",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    servers=[{"url": "https://sireai.uk/stocknx", "description": "Production"}]
)

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

JUNK_TICKERS = [
    'VSPBONDETF','VETGRIF30','GREENWETF','STANBICETF30','SIAMLETF40',
    'NEWGOLD','LOTUSHAL15','TAJSUKS1','TAJSUKS2','FGS202894',
    'FGSUK2031S4','FGS202776','MOFIREIF','FGS202770','MERGROWTH',
    'MERVALUE','NIDF','MERG','FFFBN','SFSREIT','UPDCREIT'
]

# ─── AUTH HELPERS ───────────────────────────────────────────────────────────────

def create_token(telegram_id: int, tier: str) -> str:
    payload = {
        "telegram_id": telegram_id,
        "tier": tier,
        "exp": datetime.now(UTC) + timedelta(days=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    payload = decode_token(credentials.credentials)
    telegram_id = payload.get("telegram_id")
    result = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="User not found")
    user = result.data[0]
    expires_at = user.get("expires_at")
    if expires_at:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if datetime.now(UTC) > exp:
            raise HTTPException(status_code=403, detail="Subscription expired")
    return user

def require_tier(user: dict, min_tier: str):
    tier_rank = {"free": 0, "basic": 1, "pro": 2, "admin": 3}
    user_rank = tier_rank.get(user.get("tier", "free"), 0)
    required_rank = tier_rank.get(min_tier, 1)
    if user_rank < required_rank:
        raise HTTPException(status_code=403, detail=f"This feature requires {min_tier} subscription")

def ok(data):
    return {"success": True, "data": data, "error": None}

def err(msg, code=400):
    raise HTTPException(status_code=code, detail={"success": False, "data": None, "error": msg})

# ─── AUTH ───────────────────────────────────────────────────────────────────────

@api_app.post("/api/v1/auth/register")
async def register(request: Request):
    body = await request.json()
    telegram_id = body.get("telegram_id")
    name = body.get("name", "")
    email = body.get("email", "")

    if not telegram_id:
        err("telegram_id is required")

    existing = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()

    if existing.data:
        user = existing.data[0]
        token = create_token(telegram_id, user.get("tier", "free"))
        return ok({"token": token, "user": user, "is_new": False})

    new_user = {
        "telegram_id": telegram_id,
        "name": name,
        "email": email,
        "tier": "free",
        "terms_accepted": False,
        "waitlist": False,
        "waitlist_notified": False,
        "copy_trading_enabled": False,
        "copy_trading_amount": 0,
        "message_count": 0,
        "bonus_days": 0,
    }
    result = supabase.table("users").insert(new_user).execute()
    user = result.data[0]
    token = create_token(telegram_id, "free")
    return ok({"token": token, "user": user, "is_new": True})

@api_app.post("/api/v1/auth/login")
async def login(request: Request):
    body = await request.json()
    telegram_id = body.get("telegram_id")
    email = body.get("email")

    if telegram_id:
        result = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    elif email:
        result = supabase.table("users").select("*").eq("email", email).execute()
    else:
        err("telegram_id or email required")

    if not result.data:
        err("User not found", 404)

    user = result.data[0]
    token = create_token(user["telegram_id"], user.get("tier", "free"))
    return ok({
        "token": token,
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "user": user
    })

# ─── USER ───────────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/user/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    return ok(user)

@api_app.get("/api/v1/user/status")
async def get_status(user: dict = Depends(get_current_user)):
    expires_at = user.get("expires_at")
    is_active = False
    days_remaining = 0

    if expires_at:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        is_active = now < exp
        days_remaining = max(0, (exp - now).days)

    return ok({
        "is_active": is_active,
        "tier": user.get("tier", "free"),
        "days_remaining": days_remaining,
        "expires_at": expires_at
    })

@api_app.post("/api/v1/user/update")
async def update_profile(request: Request, user: dict = Depends(get_current_user)):
    body = await request.json()
    updates = {}
    if "email" in body:
        updates["email"] = body["email"]
    if not updates:
        err("Nothing to update")
    result = supabase.table("users").update(updates).eq("telegram_id", user["telegram_id"]).execute()
    return ok(result.data[0] if result.data else user)

@api_app.get("/api/v1/user/referral")
async def get_referral(user: dict = Depends(get_current_user)):
    telegram_id = user["telegram_id"]
    referral_code = user.get("referral_code", "")

    referrals = supabase.table("referrals").select("*").eq("referrer_id", telegram_id).execute()
    rewards = supabase.table("referral_rewards").select("*").eq("referrer_id", telegram_id).execute()

    total_referrals = len(referrals.data or [])
    converting = len([r for r in (referrals.data or []) if r.get("converted")])
    total_earned = sum(r.get("amount", 0) for r in (rewards.data or []))
    pending = sum(r.get("amount", 0) for r in (rewards.data or []) if not r.get("paid"))

    return ok({
        "referral_code": referral_code,
        "referral_url": f"https://t.me/StockNxAIBot?start={referral_code}",
        "total_referrals": total_referrals,
        "converting_referrals": converting,
        "earnings_ngn": total_earned,
        "pending_payout": pending
    })

# ─── SIGNALS ────────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/signals/weekly")
async def get_weekly_signals(user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    since = (date.today() - timedelta(days=7)).isoformat()
    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .gte("created_at", since)\
        .order("created_at", desc=True)\
        .execute()
    signals = [s for s in (result.data or []) if s["ticker"] not in JUNK_TICKERS]
    return ok(signals)

@api_app.get("/api/v1/signals/daily")
async def get_daily_signals(user: dict = Depends(get_current_user)):
    require_tier(user, "pro")
    since = date.today().isoformat()
    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .gte("created_at", since)\
        .order("created_at", desc=True)\
        .limit(3)\
        .execute()
    signals = [s for s in (result.data or []) if s["ticker"] not in JUNK_TICKERS]
    return ok(signals)

@api_app.get("/api/v1/signals/active")
async def get_active_signals(user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    result = supabase.table("signals")\
        .select("*")\
        .eq("status", "active")\
        .order("created_at", desc=True)\
        .execute()
    signals = [s for s in (result.data or []) if s["ticker"] not in JUNK_TICKERS]
    return ok(signals)

@api_app.get("/api/v1/signals/{ticker}")
async def get_signal_by_ticker(ticker: str, user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    result = supabase.table("signals")\
        .select("*")\
        .eq("ticker", ticker.upper())\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    if not result.data:
        err(f"No signal found for {ticker}", 404)
    return ok(result.data[0])

# ─── PERFORMANCE ────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/performance")
async def get_performance(user: dict = Depends(get_current_user)):
    result = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .execute()
    records = [r for r in (result.data or []) if r["ticker"] not in JUNK_TICKERS]
    if not records:
        return ok({"total_closed": 0, "win_rate": 0, "average_return": 0, "total_wins": 0, "total_losses": 0})

    wins = [r for r in records if r["outcome"] == "tp1_hit"]
    losses = [r for r in records if r["outcome"] == "stopped_out"]
    win_rate = round(len(wins) / len(records) * 100, 1) if records else 0
    avg_return = round(sum(r.get("gain_percentage", 0) for r in records) / len(records), 2) if records else 0

    sorted_by_gain = sorted(records, key=lambda x: x.get("gain_percentage", 0) or 0)
    best = sorted_by_gain[-1] if sorted_by_gain else None
    worst = sorted_by_gain[0] if sorted_by_gain else None

    return ok({
        "total_closed": len(records),
        "win_rate": win_rate,
        "average_return": avg_return,
        "total_wins": len(wins),
        "total_losses": len(losses),
        "best_signal": best,
        "worst_signal": worst
    })

@api_app.get("/api/v1/performance/history")
async def get_signal_history(
    user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    outcome: Optional[str] = None,
    ticker: Optional[str] = None
):
    query = supabase.table("signal_history")\
        .select("*")\
        .neq("outcome", "pending")\
        .order("week_start", desc=True)

    if outcome:
        query = query.eq("outcome", outcome)
    if ticker:
        query = query.eq("ticker", ticker.upper())

    result = query.execute()
    records = [r for r in (result.data or []) if r["ticker"] not in JUNK_TICKERS]

    start = (page - 1) * limit
    paginated = records[start:start + limit]

    return ok({
        "total": len(records),
        "page": page,
        "limit": limit,
        "results": paginated
    })

@api_app.get("/api/v1/performance/sectors")
async def get_sector_performance(user: dict = Depends(get_current_user)):
    since = (date.today() - timedelta(days=30)).isoformat()
    result = supabase.table("stocks").select("ticker, company, change, trade_date").gte("trade_date", since).execute()

    sector_map = {
        "Banking": ["GTCO","ZENITHBANK","ACCESSCORP","UBA","FIDELITYBK","FCMB","WEMABANK","STANBIC","FIRSTHOLDCO","JAIZBANK"],
        "Telecoms": ["MTNN","AIRTELAFRI"],
        "Oil & Gas": ["SEPLAT","OANDO","TOTAL","ETERNA","CONOIL","ARADEL"],
        "Consumer Goods": ["DANGSUGAR","NASCON","NESTLE","UNILEVER","CADBURY","NB","GUINNESS","BUAFOODS"],
        "Cement": ["DANGCEM","BUACEMENT","WAPCO"],
        "Insurance": ["AIICO","MANSARD","CUSTODIAN","NEM"],
    }

    def get_sector(ticker):
        for sector, tickers in sector_map.items():
            if ticker in tickers:
                return sector
        return None

    sector_data = {}
    for stock in (result.data or []):
        sector = get_sector(stock["ticker"])
        if not sector:
            continue
        try:
            val = float(stock.get("change","0%").strip("'\" ").replace("%","").replace("+",""))
            if sector not in sector_data:
                sector_data[sector] = []
            if val != 0:
                sector_data[sector].append(val)
        except:
            continue

    history_result = supabase.table("signal_history").select("ticker, outcome").neq("outcome", "pending").execute()
    sector_signals = {}
    for r in (history_result.data or []):
        sector = get_sector(r["ticker"])
        if not sector:
            continue
        if sector not in sector_signals:
            sector_signals[sector] = {"wins": 0, "total": 0}
        sector_signals[sector]["total"] += 1
        if r["outcome"] == "tp1_hit":
            sector_signals[sector]["wins"] += 1

    output = []
    for sector, changes in sector_data.items():
        avg = round(sum(changes) / len(changes), 2) if changes else 0
        up = sum(1 for c in changes if c > 0)
        sig = sector_signals.get(sector, {})
        win_rate = round(sig["wins"] / sig["total"] * 100, 1) if sig.get("total") else 0
        output.append({
            "sector": sector,
            "avg_change": avg,
            "up_rate": round(up / len(changes) * 100, 1) if changes else 0,
            "signal_win_rate": win_rate,
            "total_signals": sig.get("total", 0)
        })

    output.sort(key=lambda x: x["avg_change"], reverse=True)
    return ok(output)

# ─── STOCKS ─────────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/stocks/movers")
async def get_movers(
    user: dict = Depends(get_current_user),
    type: str = Query("gainers"),
    limit: int = Query(10, ge=1, le=50)
):
    result = supabase.table("stocks")\
        .select("ticker, company, price, change, volume")\
        .eq("trade_date", date.today().isoformat())\
        .execute()

    stocks = []
    for s in (result.data or []):
        if s["ticker"] in JUNK_TICKERS:
            continue
        try:
            val = float(s.get("change","0%").strip("'\" ").replace("%","").replace("+",""))
            if val != 0:
                stocks.append({**s, "_change_val": val})
        except:
            continue

    if type == "losers":
        stocks.sort(key=lambda x: x["_change_val"])
    else:
        stocks.sort(key=lambda x: x["_change_val"], reverse=True)

    result_list = []
    for s in stocks[:limit]:
        s.pop("_change_val", None)
        result_list.append(s)

    return ok(result_list)

@api_app.get("/api/v1/stocks/search")
async def search_stocks(
    user: dict = Depends(get_current_user),
    q: str = Query(..., min_length=1)
):
    result = supabase.table("stocks")\
        .select("ticker, company, price, change, signal")\
        .order("trade_date", desc=True)\
        .execute()

    q_upper = q.upper()
    seen = set()
    matches = []
    for s in (result.data or []):
        ticker = s["ticker"]
        if ticker in seen or ticker in JUNK_TICKERS:
            continue
        if q_upper in ticker or q_upper in s.get("company", "").upper():
            seen.add(ticker)
            matches.append(s)
        if len(matches) >= 20:
            break

    return ok(matches)

@api_app.get("/api/v1/stocks/{ticker}/history")
async def get_stock_history(
    ticker: str,
    user: dict = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90)
):
    since = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("stocks")\
        .select("trade_date, price, change, volume")\
        .eq("ticker", ticker.upper())\
        .gte("trade_date", since)\
        .order("trade_date", desc=False)\
        .execute()
    return ok(result.data or [])

@api_app.get("/api/v1/stocks/{ticker}/technical")
async def get_technical(ticker: str, user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    since = (date.today() - timedelta(days=60)).isoformat()
    result = supabase.table("stocks")\
        .select("price, volume, trade_date")\
        .eq("ticker", ticker.upper())\
        .gte("trade_date", since)\
        .order("trade_date", desc=False)\
        .execute()

    records = result.data or []
    if len(records) < 5:
        err(f"Not enough price history for {ticker}", 404)

    prices = [clean_price(r["price"]) for r in records if clean_price(r["price"]) > 0]
    volumes = [clean_volume(r.get("volume", "0")) for r in records]
    analysis = full_technical_analysis(prices, volumes)
    return ok(analysis)

@api_app.get("/api/v1/stocks/{ticker}")
async def get_stock(ticker: str, user: dict = Depends(get_current_user)):
    result = supabase.table("stocks")\
        .select("*")\
        .eq("ticker", ticker.upper())\
        .order("trade_date", desc=True)\
        .limit(1)\
        .execute()

    if not result.data:
        err(f"Stock {ticker} not found", 404)

    s = result.data[0]
    vol = clean_volume(s.get("volume", "0"))
    price_val = clean_price(s.get("price", "0"))
    naira_value = vol * price_val
    is_liquid = naira_value >= 500_000

    liquidity_warning = None
    if naira_value == 0:
        liquidity_warning = "No trading activity today. Treat with extreme caution."
    elif naira_value < 500_000:
        liquidity_warning = f"Only ₦{naira_value:,.0f} traded today. This stock is illiquid — you may struggle to exit your position."

    return ok({
        "ticker": s["ticker"],
        "company": s.get("company", ""),
        "price": price_val,
        "change": s.get("change", ""),
        "signal": s.get("signal", ""),
        "volume": s.get("volume", ""),
        "naira_value_traded": naira_value,
        "is_liquid": is_liquid,
        "trade_date": s.get("trade_date", ""),
        "liquidity_warning": liquidity_warning
    })

# ─── MARKET INTELLIGENCE ────────────────────────────────────────────────────────

@api_app.get("/api/v1/market/breadth")
async def get_breadth(user: dict = Depends(get_current_user)):
    today = date.today().isoformat()
    result = supabase.table("stocks").select("ticker, change").eq("trade_date", today).execute()
    stocks = result.data or []

    up = down = flat = 0
    for s in stocks:
        if s["ticker"] in JUNK_TICKERS:
            continue
        try:
            val = float(s.get("change","0%").strip("'\" ").replace("%","").replace("+",""))
            if val > 0: up += 1
            elif val < 0: down += 1
            else: flat += 1
        except:
            flat += 1

    total = up + down + flat
    breadth = round(up / (up + down) * 100, 1) if (up + down) > 0 else 50

    return ok({
        "breadth": breadth,
        "stocks_up": up,
        "stocks_down": down,
        "stocks_flat": flat,
        "total_stocks": total,
        "signal_safe": breadth >= 40,
        "trade_date": today
    })

@api_app.get("/api/v1/market/volume")
async def get_volume_leaders(
    user: dict = Depends(get_current_user),
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(10, ge=1, le=50)
):
    require_tier(user, "basic")
    since = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("stocks")\
        .select("ticker, company, volume, trade_date, price, change")\
        .gte("trade_date", since)\
        .execute()

    from collections import defaultdict
    ticker_data = defaultdict(list)
    for s in (result.data or []):
        if s["ticker"] in JUNK_TICKERS:
            continue
        vol = clean_volume(s.get("volume", "0"))
        if vol > 0:
            ticker_data[s["ticker"]].append({
                "vol": vol, "date": s["trade_date"],
                "price": s.get("price",""), "change": s.get("change",""),
                "company": s.get("company","")
            })

    spikes = []
    for ticker, entries in ticker_data.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda x: x["date"])
        latest = entries[-1]["vol"]
        avg = sum(e["vol"] for e in entries[:-1]) / len(entries[:-1])
        if avg > 0:
            ratio = latest / avg
            if ratio >= 1.5:
                spikes.append({
                    "ticker": ticker,
                    "company": entries[-1]["company"],
                    "volume_ratio": round(ratio, 2),
                    "today_volume": latest,
                    "avg_volume": round(avg),
                    "price": entries[-1]["price"],
                    "change": entries[-1]["change"]
                })

    spikes.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return ok(spikes[:limit])

@api_app.get("/api/v1/market/volatility")
async def get_volatility(
    user: dict = Depends(get_current_user),
    ticker: Optional[str] = None
):
    require_tier(user, "basic")
    since = (date.today() - timedelta(days=30)).isoformat()

    query = supabase.table("stocks").select("ticker, change, trade_date")
    if ticker:
        query = query.eq("ticker", ticker.upper())
    query = query.gte("trade_date", since)
    result = query.execute()

    from collections import defaultdict
    ticker_changes = defaultdict(list)
    for s in (result.data or []):
        if s["ticker"] in JUNK_TICKERS:
            continue
        try:
            val = abs(float(s.get("change","0%").strip("'\" ").replace("%","").replace("+","")))
            if val != 0:
                ticker_changes[s["ticker"]].append(val)
        except:
            continue

    if ticker:
        t = ticker.upper()
        changes = ticker_changes.get(t, [])
        if not changes:
            err(f"No volatility data for {t}", 404)
        avg = sum(changes) / len(changes)
        rating = "High" if avg > 3 else "Medium" if avg > 1.5 else "Low"
        return ok({
            "ticker": t,
            "avg_daily_move": round(avg, 2),
            "max_daily_move": round(max(changes), 2),
            "volatility_rating": rating,
            "days_analyzed": len(changes)
        })

    profiles = [
        {"ticker": t, "avg_daily_move": round(sum(c)/len(c), 2)}
        for t, c in ticker_changes.items() if len(c) >= 5
    ]
    profiles.sort(key=lambda x: x["avg_daily_move"])
    return ok({
        "most_stable": profiles[:10],
        "most_volatile": list(reversed(profiles[-10:]))
    })

@api_app.get("/api/v1/market/best-days")
async def get_best_days(user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    since = (date.today() - timedelta(days=60)).isoformat()
    result = supabase.table("stocks").select("change, trade_date").gte("trade_date", since).execute()

    from collections import defaultdict
    import datetime as dt
    day_data = defaultdict(list)
    for s in (result.data or []):
        try:
            d = dt.date.fromisoformat(s["trade_date"])
            day = d.strftime("%A")
            val = float(s.get("change","0%").strip("'\" ").replace("%","").replace("+",""))
            if val != 0:
                day_data[day].append(val)
        except:
            continue

    order = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
    output = []
    for day in order:
        if day in day_data:
            changes = day_data[day]
            avg = sum(changes) / len(changes)
            up = sum(1 for c in changes if c > 0)
            output.append({
                "day": day,
                "avg_return": round(avg, 2),
                "up_rate": round(up / len(changes) * 100, 1)
            })

    return ok(output)

@api_app.get("/api/v1/market/filings")
async def get_filings(
    user: dict = Depends(get_current_user),
    impact: Optional[str] = None,
    ticker: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    require_tier(user, "basic")
    query = supabase.table("filings")\
        .select("ticker, filing_type, summary, sentiment, impact, source, scraped_at")\
        .order("scraped_at", desc=True)

    if impact:
        query = query.eq("impact", impact)
    if ticker:
        query = query.eq("ticker", ticker.upper())

    result = query.limit(limit).execute()
    return ok(result.data or [])

# ─── WATCHLIST ──────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/watchlist")
async def get_watchlist(user: dict = Depends(get_current_user)):
    telegram_id = user["telegram_id"]
    result = supabase.table("watchlist").select("*").eq("telegram_id", telegram_id).execute()
    items = result.data or []

    enriched = []
    for item in items:
        stock = supabase.table("stocks")\
            .select("price, change, signal")\
            .eq("ticker", item["ticker"])\
            .order("trade_date", desc=True)\
            .limit(1)\
            .execute()
        stock_data = stock.data[0] if stock.data else {}
        enriched.append({
            "ticker": item["ticker"],
            "company": stock_data.get("company", ""),
            "price": stock_data.get("price", ""),
            "change": stock_data.get("change", ""),
            "signal": stock_data.get("signal", ""),
            "added_at": item.get("created_at", "")
        })

    return ok(enriched)

@api_app.post("/api/v1/watchlist/{ticker}")
async def add_watchlist(ticker: str, user: dict = Depends(get_current_user)):
    telegram_id = user["telegram_id"]
    existing = supabase.table("watchlist")\
        .select("id")\
        .eq("telegram_id", telegram_id)\
        .eq("ticker", ticker.upper())\
        .execute()

    if existing.data:
        return ok({"message": f"{ticker.upper()} already in watchlist"})

    supabase.table("watchlist").insert({
        "telegram_id": telegram_id,
        "ticker": ticker.upper()
    }).execute()
    return ok({"message": f"{ticker.upper()} added to watchlist"})

@api_app.delete("/api/v1/watchlist/{ticker}")
async def remove_watchlist(ticker: str, user: dict = Depends(get_current_user)):
    telegram_id = user["telegram_id"]
    supabase.table("watchlist")\
        .delete()\
        .eq("telegram_id", telegram_id)\
        .eq("ticker", ticker.upper())\
        .execute()
    return ok({"message": f"{ticker.upper()} removed from watchlist"})

# ─── PAYMENTS ───────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/payments/plans")
async def get_plans():
    return ok([
        {
            "id": "basic",
            "name": "Basic",
            "price_ngn": 5999,
            "duration_days": 30,
            "features": [
                "5 weekly NGX signals every Monday",
                "Take profit and stop loss alerts",
                "Unlimited stock lookups",
                "Full AI analysis with OracleAI",
                "Watchlist with daily updates",
                "Market intelligence tools",
                "NGX regulatory filing alerts"
            ]
        },
        {
            "id": "pro",
            "name": "Pro",
            "price_ngn": 9999,
            "duration_days": 30,
            "features": [
                "Everything in Basic",
                "Daily signals Tuesday to Friday",
                "Full portfolio audit with PDF report",
                "Priority signal alerts"
            ]
        }
    ])

@api_app.post("/api/v1/payments/initiate")
async def initiate_payment(request: Request, user: dict = Depends(get_current_user)):
    import httpx
    from app.config import PAYSTACK_SECRET_KEY, PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN

    body = await request.json()
    plan = body.get("plan", "basic")
    email = body.get("email") or user.get("email", "")

    if not email:
        err("Email is required for payment")

    plan_code = PAYSTACK_PRO_PLAN if plan == "pro" else PAYSTACK_BASIC_PLAN
    amount = 999900 if plan == "pro" else 599900  # kobo

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            json={
                "email": email,
                "amount": amount,
                "plan": plan_code,
                "metadata": {"telegram_id": user["telegram_id"], "plan": plan},
                "callback_url": "https://sireai.uk/payment/success"
            }
        )
        data = response.json()

    if not data.get("status"):
        err("Failed to initialize payment")

    return ok({
        "payment_url": data["data"]["authorization_url"],
        "reference": data["data"]["reference"],
        "amount": amount
    })

@api_app.get("/api/v1/payments/verify/{reference}")
async def verify_payment(reference: str, user: dict = Depends(get_current_user)):
    import httpx
    from app.config import PAYSTACK_SECRET_KEY

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        )
        data = response.json()

    if not data.get("status") or data["data"]["status"] != "success":
        return ok({"status": "pending", "tier": user.get("tier"), "expires_at": user.get("expires_at")})

    metadata = data["data"].get("metadata", {})
    plan = metadata.get("plan", "basic")
    tier = "pro" if plan == "pro" else "basic"

    new_expiry = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    supabase.table("users").update({
        "tier": tier,
        "expires_at": new_expiry,
        "subscribed_at": datetime.now(UTC).isoformat()
    }).eq("telegram_id", user["telegram_id"]).execute()

    return ok({"status": "success", "tier": tier, "expires_at": new_expiry})

# ─── AI CHAT ────────────────────────────────────────────────────────────────────

@api_app.post("/api/v1/ai/chat")
async def ai_chat(request: Request, user: dict = Depends(get_current_user)):
    require_tier(user, "basic")
    body = await request.json()
    message = body.get("message", "").strip()
    history = body.get("conversation_history", [])

    if not message:
        err("message is required")

    from app.ai import get_ai_response
    tier = user.get("tier", "basic")
    response_text, updated_history = get_ai_response(message, history, tier)

    supabase.table("users")\
        .update({"message_count": (user.get("message_count", 0) or 0) + 1})\
        .eq("telegram_id", user["telegram_id"])\
        .execute()

    return ok({
        "response": response_text,
        "updated_history": updated_history
    })

# ─── HEALTH ──────────────────────────────────────────────────────────────────────

@api_app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "StockNX API", "version": "1.0.0"}



@api_app.get("/api/v1")
async def root():
    return {
        "service": "StockNX API",
        "version": "1.0.0",
        "base_url": "https://sireai.uk/stocknx/api/v1",
        "docs": "https://sireai.uk/stocknx/api/v1/docs",
        "endpoints": {
            "auth": {
                "POST /auth/register": "Register new user",
                "POST /auth/login": "Login and get token"
            },
            "user": {
                "GET /user/profile": "Get user profile (auth required)",
                "GET /user/status": "Check subscription status (auth required)",
                "POST /user/update": "Update profile (auth required)",
                "GET /user/referral": "Get referral info (auth required)"
            },
            "signals": {
                "GET /signals/weekly": "This week's signals (Basic+)",
                "GET /signals/daily": "Today's daily signals (Pro only)",
                "GET /signals/active": "All active signals (Basic+)",
                "GET /signals/{ticker}": "Signal for specific stock (Basic+)"
            },
            "performance": {
                "GET /performance": "Overall track record",
                "GET /performance/history": "Full signal history",
                "GET /performance/sectors": "Performance by sector"
            },
            "stocks": {
                "GET /stocks/movers": "Top gainers and losers",
                "GET /stocks/search?q=": "Search stocks",
                "GET /stocks/{ticker}": "Stock price and data",
                "GET /stocks/{ticker}/history": "Price history",
                "GET /stocks/{ticker}/technical": "Technical analysis (Basic+)"
            },
            "market": {
                "GET /market/breadth": "Market health indicator",
                "GET /market/volume": "Volume leaders (Basic+)",
                "GET /market/volatility": "Volatility profiles (Basic+)",
                "GET /market/best-days": "Best trading days (Basic+)",
                "GET /market/filings": "NGX regulatory filings (Basic+)"
            },
            "watchlist": {
                "GET /watchlist": "Get watchlist (auth required)",
                "POST /watchlist/{ticker}": "Add to watchlist (auth required)",
                "DELETE /watchlist/{ticker}": "Remove from watchlist (auth required)"
            },
            "payments": {
                "GET /payments/plans": "Available subscription plans",
                "POST /payments/initiate": "Start payment (auth required)",
                "GET /payments/verify/{reference}": "Verify payment (auth required)"
            },
            "ai": {
                "POST /ai/chat": "Chat with OracleAI (Basic+)"
            },
            "health": {
                "GET /health": "API health check"
            }
        }
    }