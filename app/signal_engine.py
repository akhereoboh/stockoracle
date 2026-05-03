import logging
from app.database import supabase
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

def clean_price(price_str: str) -> float:
    try:
        return float(price_str.replace("₦", "").replace(",", "").strip())
    except:
        return 0.0

def clean_change(change_str: str) -> float:
    try:
        return float(change_str.replace("%", "").strip())
    except:
        return 0.0

def get_latest_stocks() -> list:
    result = supabase.table("stocks")\
        .select("*")\
        .order("scraped_at", desc=True)\
        .limit(445)\
        .execute()
    return result.data or []

def score_stock(stock: dict) -> float:
    score = 0.0
    signal = stock.get("signal", "").upper()
    change = clean_change(stock.get("change", "0%"))
    price = clean_price(stock.get("price", "₦0"))

    # signal score
    if "BUY" in signal:
        score += 40
    elif "HOLD" in signal:
        score += 10
    elif "SELL" in signal or "NO DATA" in signal:
        return 0.0  # exclude sells and no data

    # positive momentum bonus
    if change > 0:
        score += min(change * 2, 20)  # cap at 20 points

    # penalise extreme moves (likely manipulation)
    if change > 9:
        score -= 15

    # penalise very low price stocks (under ₦1)
    if price < 1:
        score -= 20

    return score

def generate_targets(price: float) -> dict:
    return {
        "entry": price,
        "tp1": round(price * 1.06, 2),   # 6% gain
        "tp2": round(price * 1.12, 2),   # 12% gain
        "stop_loss": round(price * 0.96, 2)  # 4% loss
    }

def run_signal_engine() -> list:
    logger.info("Running signal engine...")
    stocks = get_latest_stocks()

    if not stocks:
        logger.warning("No stocks found in database")
        return []

    scored = []
    for stock in stocks:
        score = score_stock(stock)
        if score > 0:
            scored.append((score, stock))

    # sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # take top 5
    top5 = scored[:5]
    signals = []

    for score, stock in top5:
        price = clean_price(stock["price"])
        targets = generate_targets(price)

        signal = {
            "ticker": stock["ticker"],
            "market": "NGX",
            "entry_price": targets["entry"],
            "tp1": targets["tp1"],
            "tp2": targets["tp2"],
            "stop_loss": targets["stop_loss"],
            "status": "active",
            "created_at": datetime.now(UTC).isoformat()
        }
        signals.append(signal)
        logger.info(f"Signal: {stock['ticker']} | Score: {score:.1f} | Entry: ₦{price}")

    # save to supabase
    if signals:
        supabase.table("signals").insert(signals).execute()
        logger.info(f"Saved {len(signals)} signals to Supabase")

    return signals