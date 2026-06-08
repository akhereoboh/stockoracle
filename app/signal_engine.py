import logging
from app.database import supabase
from datetime import datetime, UTC, date, timedelta
from collections import defaultdict
import re

logger = logging.getLogger(__name__)

def is_tradeable_equity(ticker: str, company: str = "") -> bool:
    
    # must be valid ticker format: letters and numbers, starts with letter
    if not re.match(r'^[A-Z][A-Z0-9]{1,14}$', ticker):
        return False
    
    # 4+ consecutive digits = bond/dated instrument
    if re.search(r'\d{4}', ticker):
        return False
    
    # explicit non-equity prefixes only
    non_equity_prefixes = [
        'NGX', 'ASI', 'TAJSUKS', 'MECU', 'COLE',
        'SOVRIGHTS', 'UNITYRIGHTS',
    ]
    for prefix in non_equity_prefixes:
        if ticker.startswith(prefix):
            return False
    
    # rights issues — RR prefix
    if ticker.startswith('RR'):
        return False
    
    # commercial paper — CP prefix  
    if re.match(r'^CP\d', ticker):
        return False
    
    # pure numbers
    if ticker.isdigit():
        return False
    
    # company name: only exclude if clearly a fund/bond instrument
    if company:
        company_upper = company.upper()
        # very specific phrases only — not single words
        non_equity_phrases = [
            'MONEY MARKET FUND',
            'FIXED INCOME FUND', 
            'BOND FUND',
            'SUKUK',
            'TREASURY BILL',
            '% FGS',      # government securities format
            '% FGN',
            '% TSL',
            '% CEMC',
            'RIGHTS ISSUE',
            '2025 RIGHTS',
            '2026 RIGHTS',
            'INFRASTRUCTURE FUND',
            'LAST UPDATED',
            'HOLD SIGNALS',
            'SPREAD', 'REAL ESTATE INVEST', 'REIT',
            'BLANCED FUND', 'EQUITY FUND', 'GROWTH FUND',
            'NGX', 'ASI', 'TAJSUKS', 'MECU', 'COLE',
            'SOVRIGHTS', 'UNITYRIGHTS', 'MOFIREIF',
            'FFFBN', 'FFUNC', 'FFLEGY', 'FFFSDHC',
            'FFIONE', 'FFFRONT', 'CNIF', 'AVAIF',
            'MERVAL', 'MERG', 'NIDF',
            'VETGOODS', 'VETBANK', 'SIAMLETF',
            'STANBICETF', 'GREENWETF', 'NGXPENBRD',
            'MERCER', 'MERISTEM VALUE', 'MERISTEM GROWTH',
        ]
        for phrase in non_equity_phrases:
            if phrase in company_upper:
                return False
    
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
    since = (date.today() - timedelta(days=days)).isoformat()
    result = supabase.table("stocks")\
        .select("ticker, price, change, trade_date, volume")\
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

def get_average_volume(history: list) -> float:
    volumes = []
    for h in history:
        vol = clean_volume(h.get("volume", "0")) if "volume" in h else 0
        if vol > 0:
            volumes.append(vol)
    if not volumes:
        return 0
    return sum(volumes) / len(volumes)

def get_price_trend(history: list) -> str:
    if len(history) < 5:
        return "unknown"
    prices = [clean_price(h["price"]) for h in history if clean_price(h["price"]) > 0]
    if len(prices) < 5:
        return "unknown"
    avg5 = sum(prices[-5:]) / 5
    avg10 = sum(prices) / len(prices)
    if avg5 > avg10:
        return "uptrend"
    elif avg5 < avg10 * 0.97:
        return "downtrend"
    return "sideways"

def score_stock(stock: dict, history: list) -> float:
    score = 0.0
    signal = stock.get("signal", "").upper()
    change = clean_change(stock.get("change", "0%"))
    price = clean_price(stock.get("price", "0"))
    today_volume = clean_volume(stock.get("volume", "0"))

    # hard exclusions
    if "SELL" in signal or "NO DATA" in signal:
        return 0.0

    if price < 1:
        return 0.0

 # minimum 3 days history
    if len(history) < 3:
        return 0.0

    # liquidity gate
    avg_volume = get_average_volume(history)
    if avg_volume > 0 and avg_volume < 50000 and today_volume < 50000:
        return 0.0

    # trend filter
    trend = get_price_trend(history)
    if trend == "downtrend":
        return 0.0

    # consecutive up days — only enforce strictly if enough history
    if len(history) >= 5:
        consecutive_up = count_consecutive_up_days(history)
        if consecutive_up < 2:
            return 0.0
    else:
        consecutive_up = count_consecutive_up_days(history)

    # signal score
    if "BUY" in signal:
        score += 40
    elif "HOLD" in signal:
        score += 15
    else:
        return 0.0

    # today momentum
    if 0 < change <= 9:
        score += min(change * 2, 20)
    elif change > 9:
        score -= 10

    # multi-day momentum
    momentum = calculate_momentum(history)
    if momentum > 0:
        score += min(momentum * 1.5, 25)
    elif momentum < -10:
        score -= 15

    # consistency
    consistency = calculate_consistency(history)
    score += (consistency / 100) * 15

    # volume confirmation
    if avg_volume > 0 and today_volume > 0:
        volume_ratio = today_volume / avg_volume
        if volume_ratio >= 3:
            score += 20
        elif volume_ratio >= 2:
            score += 15
        elif volume_ratio >= 1.5:
            score += 10
        elif volume_ratio >= 1:
            score += 5

    # consecutive up days bonus
    score += min(consecutive_up * 3, 15)

    # uptrend bonus
    if trend == "uptrend":
        score += 10

    # history depth bonus
    if len(history) >= 7:
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

    # market breadth check
    breadth = check_market_breadth(stocks)
    logger.info(f"Market breadth: {breadth:.1%} stocks up today")
    if breadth < 0.40:
        logger.warning(f"Market breadth too low ({breadth:.1%}) — pausing signals today")
        return []

    # extend history to 14 days for better accuracy
    logger.info("Fetching bulk history...")
    history_map = get_all_history_bulk(days=14)

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

        # minimum 60 points — high conviction only
        if score >= 60:
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


def check_market_breadth(stocks: list) -> float:
    up = 0
    total = 0
    for stock in stocks:
        change_str = stock.get("change", "").strip("'\" ")
        try:
            change_val = float(change_str.replace("%", "").replace("+", ""))
            if change_val != 0:  # only count stocks that actually moved
                total += 1
                if change_val > 0:
                    up += 1
        except:
            continue
    if total == 0:
        return 0.5
    return up / total

def count_consecutive_up_days(history: list) -> int:
    if not history:
        return 0
    sorted_h = sorted(history, key=lambda x: x.get("trade_date", ""), reverse=True)
    consecutive = 0
    for h in sorted_h:
        change = clean_change(h.get("change", "0%"))
        if change > 0:
            consecutive += 1
        else:
            break
    return consecutive