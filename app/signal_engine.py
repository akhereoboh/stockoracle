import logging
from app.database import supabase
from datetime import datetime, UTC, date, timedelta

logger = logging.getLogger(__name__)

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

def get_latest_stocks() -> list:
    today = date.today().isoformat()
    result = supabase.table("stocks")\
        .select("*")\
        .eq("trade_date", today)\
        .execute()
    return result.data or []

def get_historical_prices(ticker: str, days: int = 10) -> list:
    since = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("stocks")\
        .select("price, change, trade_date")\
        .eq("ticker", ticker)\
        .gte("trade_date", since)\
        .order("trade_date", desc=False)\
        .execute()
    return result.data or []

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

def score_stock(stock: dict, history: list) -> float:
    score = 0.0
    signal = stock.get("signal", "").upper()
    change = clean_change(stock.get("change", "0%"))
    price = clean_price(stock.get("price", "₦0"))

    # exclude sells, no data, and very cheap stocks
    if "SELL" in signal or "NO DATA" in signal:
        return 0.0
    if price < 1:
        return 0.0

    # signal score
    if "BUY" in signal:
        score += 40
    elif "HOLD" in signal:
        score += 10

    # today's momentum
    if 0 < change <= 9:
        score += min(change * 2, 20)
    elif change > 9:
        score -= 10  # suspicious pump

    # historical momentum (trend over last 10 days)
    momentum = calculate_momentum(history)
    if momentum > 0:
        score += min(momentum * 1.5, 25)
    elif momentum < -10:
        score -= 15

    # consistency (how many days were positive)
    consistency = calculate_consistency(history)
    score += (consistency / 100) * 15

    # bonus for having enough history
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

    recently_signalled = get_recently_signalled_tickers(weeks=2)
    logger.info(f"Excluding {len(recently_signalled)} recently signalled tickers")

    scored = []
    for stock in stocks:
        ticker = stock["ticker"]

        if ticker in recently_signalled:
            continue

        history = get_historical_prices(ticker, days=10)
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

    # save signals
    supabase.table("signals").insert(signals).execute()

    # save to signal history
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

    for record in active.data:
        ticker = record["ticker"]
        latest = supabase.table("stocks")\
            .select("price")\
            .eq("ticker", ticker)\
            .order("trade_date", desc=True)\
            .limit(1)\
            .execute()

        if not latest.data:
            continue

        current_price = clean_price(latest.data[0]["price"])
        entry = record["entry_price"]
        tp1 = record["tp1"]
        stop_loss = record["stop_loss"]

        if current_price >= tp1:
            outcome = "tp1_hit"
            gain = round(((current_price - entry) / entry) * 100, 2)
        elif current_price <= stop_loss:
            outcome = "stopped_out"
            gain = round(((current_price - entry) / entry) * 100, 2)
        else:
            continue

        supabase.table("signal_history").update({
            "outcome": outcome,
            "close_price": current_price,
            "gain_percentage": gain,
            "closed_at": datetime.now(UTC).isoformat()
        }).eq("id", record["id"]).execute()

        logger.info(f"{ticker} outcome: {outcome} | Gain: {gain}%")