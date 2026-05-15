import logging
from app.database import supabase
from datetime import datetime, UTC, date, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

def is_tradeable_equity(ticker: str, company: str = "") -> bool:
    import re
    
    # fast rule: 4+ consecutive digits = bond
    if re.search(r'\d{4}', ticker):
        return False
    
    # check cache first
    try:
        cached = supabase.table("ticker_classifications")\
            .select("is_equity")\
            .eq("ticker", ticker)\
            .execute()
        if cached.data:
            return cached.data[0]["is_equity"]
    except:
        pass
    
    # ask Claude
    try:
        import anthropic
        from app.config import ANTHROPIC_API_KEY
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": f"Is '{ticker}' ({company}) a tradeable equity stock listed on the Nigerian Stock Exchange (NGX)? Answer only YES or NO. Bonds, ETFs tracking bonds, government securities, sukuk, REITs, mutual funds, indices, and rights issues should be NO. Regular company stocks should be YES."
            }]
        )
        
        answer = response.content[0].text.strip().upper()
        is_equity = answer.startswith("YES")
        
        # cache the result
        supabase.table("ticker_classifications").upsert({
            "ticker": ticker,
            "is_equity": is_equity
        }).execute()
        
        logger.info(f"Classified {ticker} ({company}): {'equity' if is_equity else 'non-equity'}")
        return is_equity
        
    except Exception as e:
        logger.error(f"Classification error for {ticker}: {e}")
        # fallback: assume equity if Claude fails
        return True

def clean_price(price_str: str) -> float:
    try:
        return float(str(price_str).replace("₦", "").replace(",", "").strip())
    except:
        return 0.0

def clean_change(change_str: str) -> float:
    try:
        return float(str(change_str).replace("%", "").strip())
    except:
        return 0.0

def clean_volume(volume_str: str) -> float:
    try:
        v = str(volume_str).replace(",", "").strip()
        return float(v) if v else 0.0
    except:
        return 0.0

def get_latest_stocks() -> list:
    today = date.today().isoformat()
    result = supabase.table("stocks")\
        .select("*")\
        .eq("trade_date", today)\
        .execute()
    return result.data or []

def get_all_history_bulk(days: int = 10) -> dict:
    """Fetch all stock history in ONE query instead of one per stock"""
    since = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("stocks")\
        .select("ticker, price, change, trade_date")\
        .gte("trade_date", since)\
        .order("trade_date", desc=False)\
        .execute()
    
    history_map = defaultdict(list)
    for row in (result.data or []):
        history_map[row["ticker"]].append(row)
    
    return dict(history_map)

def get_recently_signalled_tickers(weeks: int = 2) -> set:
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    result = supabase.table("signal_history")\
        .select("ticker")\
        .gte("week_start", since)\
        .execute()
    return {r["ticker"] for r in (result.data or [])}

def calculate_momentum(history: list) -> float:
    if len(history) < 2:
        return 0.0
    prices = [clean_price(h["price"]) for h in history if clean_price(h["price"]) > 0]
    if len(prices) < 2:
        return 0.0
    oldest = prices[0]
    newest = prices[-1]
    if oldest == 0:
        return 0.0
    return ((newest - oldest) / oldest) * 100

def calculate_consistency(history: list) -> float:
    if not history:
        return 0.0
    changes = [clean_change(h["change"]) for h in history]
    positive_days = sum(1 for c in changes if c > 0)
    return (positive_days / len(changes)) * 100

def calculate_volume_score(stock: dict, history: list) -> float:
    """Score based on volume relative to recent average"""
    try:
        today_volume = clean_volume(stock.get("volume", "0"))
        if today_volume == 0:
            return 0.0
        
        if len(history) < 3:
            return 5.0  # small bonus if no history to compare
        
        historical_volumes = [
            clean_volume(h.get("volume", "0")) 
            for h in history 
            if clean_volume(h.get("volume", "0")) > 0
        ]
        
        if not historical_volumes:
            return 0.0
        
        avg_volume = sum(historical_volumes) / len(historical_volumes)
        if avg_volume == 0:
            return 0.0
        
        volume_ratio = today_volume / avg_volume
        
        if volume_ratio >= 3:
            return 20.0  # massive volume spike
        elif volume_ratio >= 2:
            return 15.0  # strong volume spike
        elif volume_ratio >= 1.5:
            return 10.0  # moderate volume increase
        elif volume_ratio >= 1:
            return 5.0   # above average volume
        else:
            return 0.0   # below average volume
    except:
        return 0.0

def score_stock(stock: dict, history: list) -> float:
    score = 0.0
    signal = stock.get("signal", "").upper()
    change = clean_change(stock.get("change", "0%"))
    price = clean_price(stock.get("price", "₦0"))

    # hard exclusions
    if "SELL" in signal or "NO DATA" in signal:
        return 0.0
    if price < 1:
        return 0.0

    # signal score (40 points max)
    if "BUY" in signal:
        score += 40
    elif "HOLD" in signal:
        score += 10

    # today's momentum (20 points max)
    if 0 < change <= 9:
        score += min(change * 2, 20)
    elif change > 9:
        score -= 10  # suspicious pump

    # multi-day momentum (25 points max)
    momentum = calculate_momentum(history)
    if momentum > 0:
        score += min(momentum * 1.5, 25)
    elif momentum < -10:
        score -= 15

    # consistency score (15 points max)
    consistency = calculate_consistency(history)
    score += (consistency / 100) * 15

    # volume score (20 points max)
    volume_score = calculate_volume_score(stock, history)
    score += volume_score

    # history depth bonus (5 points)
    if len(history) >= 5:
        score += 5

    return score

def generate_targets(price: float) -> dict:
    return {
        "entry_price": price,
        "tp1": round(price * 1.06, 2),
        "tp2": round(price * 1.12, 2),
        "stop_loss": round(price * 0.96, 2)
    }

def run_signal_engine() -> list:
    logger.info("Running signal engine...")

    stocks = get_latest_stocks()
    if not stocks:
        logger.warning("No stocks found for today")
        return []

    logger.info("Fetching bulk history...")
    history_map = get_all_history_bulk(days=10)
    
    recently_signalled = get_recently_signalled_tickers(weeks=2)
    logger.info(f"Excluding {len(recently_signalled)} recently signalled tickers")

    scored = []
    for stock in stocks:
        ticker = stock["ticker"]
        company = stock.get("company", "")

        if not is_tradeable_equity(ticker, company):
            continue

        if ticker in recently_signalled:
            continue

        history = history_map.get(ticker, [])
        score = score_stock(stock, history)

        if score > 0:
            scored.append((score, stock, history))

    scored.sort(key=lambda x: x[0], reverse=True)
    top5 = scored[:5]

    if not top5:
        logger.warning("No qualifying stocks found")
        return []

    signals = []
    history_records = []
    week_start = date.today().isoformat()

    for score, stock, history in top5:
        price = clean_price(stock["price"])
        targets = generate_targets(price)

        signal = {
            "ticker": stock["ticker"],
            "market": "NGX",
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
            **targets
        }
        signals.append(signal)

        history_record = {
            "ticker": stock["ticker"],
            "week_start": week_start,
            **targets
        }
        history_records.append(history_record)

        logger.info(f"Signal: {stock['ticker']} | Score: {score:.1f} | Entry: ₦{price} | History: {len(history)} days")

    supabase.table("signals").insert(signals).execute()
    supabase.table("signal_history").upsert(
        history_records, on_conflict="ticker,week_start"
    ).execute()

    logger.info(f"Saved {len(signals)} signals")
    return signals

def update_signal_outcomes():
    logger.info("Checking signal outcomes...")
    
    active = supabase.table("signal_history")\
        .select("*")\
        .eq("outcome", "pending")\
        .execute()

    if not active.data:
        return

    tickers = [r["ticker"] for r in active.data]
    
    # fetch all latest prices in one query
    latest_prices = {}
    result = supabase.table("stocks")\
        .select("ticker, price, trade_date")\
        .in_("ticker", tickers)\
        .order("trade_date", desc=True)\
        .execute()
    
    for row in (result.data or []):
        if row["ticker"] not in latest_prices:
            latest_prices[row["ticker"]] = clean_price(row["price"])

    for record in active.data:
        ticker = record["ticker"]
        current_price = latest_prices.get(ticker)
        
        if not current_price:
            continue

        entry = record["entry_price"]
        tp1 = record["tp1"]
        stop_loss = record["stop_loss"]

        if current_price >= tp1:
            outcome = "tp1_hit"
        elif current_price <= stop_loss:
            outcome = "stopped_out"
        else:
            continue

        gain = round(((current_price - entry) / entry) * 100, 2)

        supabase.table("signal_history").update({
            "outcome": outcome,
            "close_price": current_price,
            "gain_percentage": gain,
            "closed_at": datetime.now(UTC).isoformat()
        }).eq("id", record["id"]).execute()

        logger.info(f"{ticker} outcome: {outcome} | Gain: {gain}%")


