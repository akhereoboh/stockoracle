import logging
from typing import Optional
import math

logger = logging.getLogger(__name__)

def calculate_rsi(prices: list, period: int = 14) -> Optional[float]:
    """
    RSI — Relative Strength Index
    Above 70: overbought (likely to pull back)
    Below 30: oversold (likely to bounce)
    50-70: bullish momentum
    30-50: bearish momentum
    """
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    # initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # smooth subsequent values
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD — Moving Average Convergence Divergence
    macd_line > signal_line: bullish
    macd_line < signal_line: bearish
    crossover (macd crosses above signal): buy signal
    crossunder (macd crosses below signal): sell signal
    """
    if len(prices) < slow + signal:
        return {"macd": None, "signal": None, "histogram": None, "crossover": None}
    
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_values = [sum(data[:period]) / period]
        for price in data[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values
    
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    
    # align lengths
    diff = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[diff:]
    
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    
    if len(macd_line) < signal:
        return {"macd": None, "signal": None, "histogram": None, "crossover": None}
    
    signal_line = ema(macd_line, signal)
    
    # align
    diff2 = len(macd_line) - len(signal_line)
    macd_aligned = macd_line[diff2:]
    
    current_macd = round(macd_aligned[-1], 4)
    current_signal = round(signal_line[-1], 4)
    histogram = round(current_macd - current_signal, 4)
    
    # detect crossover
    crossover = None
    if len(macd_aligned) >= 2 and len(signal_line) >= 2:
        prev_macd = macd_aligned[-2]
        prev_signal = signal_line[-2]
        if prev_macd <= prev_signal and current_macd > current_signal:
            crossover = "bullish"  # macd crossed above signal — buy
        elif prev_macd >= prev_signal and current_macd < current_signal:
            crossover = "bearish"  # macd crossed below signal — sell
    
    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": histogram,
        "crossover": crossover
    }

def calculate_bollinger_bands(prices: list, period: int = 20, std_dev: int = 2) -> dict:
    """
    Bollinger Bands
    Price near upper band: overbought
    Price near lower band: oversold
    Band squeeze: low volatility, big move coming
    """
    if len(prices) < period:
        return {"upper": None, "middle": None, "lower": None, "position": None, "squeeze": None}
    
    recent = prices[-period:]
    middle = sum(recent) / period
    
    variance = sum((p - middle) ** 2 for p in recent) / period
    std = math.sqrt(variance)
    
    upper = round(middle + (std_dev * std), 2)
    lower = round(middle - (std_dev * std), 2)
    middle = round(middle, 2)
    
    current_price = prices[-1]
    band_width = upper - lower
    
    # position within bands (0 = lower, 1 = upper)
    if band_width > 0:
        position = (current_price - lower) / band_width
        position = round(position, 2)
    else:
        position = 0.5
    
    # squeeze: band width less than 5% of price
    squeeze = band_width < (middle * 0.05)
    
    if position >= 0.8:
        zone = "overbought"
    elif position <= 0.2:
        zone = "oversold"
    else:
        zone = "neutral"
    
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "position": position,
        "zone": zone,
        "squeeze": squeeze,
        "band_width_pct": round(band_width / middle * 100, 2)
    }

def calculate_support_resistance(prices: list, tolerance: float = 0.02) -> dict:
    """
    Find support and resistance levels from price history.
    Support: price level the stock has bounced from multiple times
    Resistance: price level the stock has failed to break multiple times
    """
    if len(prices) < 10:
        return {"support": None, "resistance": None}
    
    # find local minima (support) and maxima (resistance)
    supports = []
    resistances = []
    
    for i in range(2, len(prices) - 2):
        # local minimum
        if prices[i] < prices[i-1] and prices[i] < prices[i+1] and \
           prices[i] < prices[i-2] and prices[i] < prices[i+2]:
            supports.append(prices[i])
        # local maximum
        if prices[i] > prices[i-1] and prices[i] > prices[i+1] and \
           prices[i] > prices[i-2] and prices[i] > prices[i+2]:
            resistances.append(prices[i])
    
    current_price = prices[-1]
    
    # find nearest support below current price
    support_levels = [s for s in supports if s < current_price * (1 - tolerance)]
    nearest_support = max(support_levels) if support_levels else min(prices)
    
    # find nearest resistance above current price
    resistance_levels = [r for r in resistances if r > current_price * (1 + tolerance)]
    nearest_resistance = min(resistance_levels) if resistance_levels else max(prices)
    
    return {
        "support": round(nearest_support, 2),
        "resistance": round(nearest_resistance, 2)
    }

def calculate_volume_trend(volumes: list, prices: list) -> str:
    """
    Volume trend analysis.
    Rising volume on up days + falling volume on down days = healthy trend
    Rising volume on down days = distribution (bearish)
    """
    if len(volumes) < 5 or len(prices) < 5:
        return "unknown"
    
    up_day_volumes = []
    down_day_volumes = []
    
    for i in range(1, len(prices)):
        if i >= len(volumes):
            break
        if prices[i] > prices[i-1]:
            up_day_volumes.append(volumes[i])
        elif prices[i] < prices[i-1]:
            down_day_volumes.append(volumes[i])
    
    if not up_day_volumes or not down_day_volumes:
        return "unknown"
    
    avg_up_vol = sum(up_day_volumes) / len(up_day_volumes)
    avg_down_vol = sum(down_day_volumes) / len(down_day_volumes)
    
    if avg_up_vol > avg_down_vol * 1.2:
        return "accumulation"  # buying pressure dominant
    elif avg_down_vol > avg_up_vol * 1.2:
        return "distribution"  # selling pressure dominant
    return "neutral"

def full_technical_analysis(prices: list, volumes: list = None) -> dict:
    """
    Run all technical indicators and return a unified analysis
    """
    if not prices or len(prices) < 5:
        return {"error": "insufficient data"}
    
    rsi = calculate_rsi(prices)
    macd = calculate_macd(prices)
    bb = calculate_bollinger_bands(prices)
    sr = calculate_support_resistance(prices)
    vol_trend = calculate_volume_trend(volumes or [], prices) if volumes else "unknown"
    
    # generate overall signal
    bullish_signals = 0
    bearish_signals = 0
    
    if rsi is not None:
        if rsi < 40:
            bullish_signals += 1  # oversold = potential bounce
        elif rsi > 65:
            bearish_signals += 1  # overbought = potential pullback
        elif 45 <= rsi <= 65:
            bullish_signals += 1  # healthy momentum
    
    if macd["macd"] is not None:
        if macd["macd"] > macd["signal"]:
            bullish_signals += 1
        else:
            bearish_signals += 1
        if macd["crossover"] == "bullish":
            bullish_signals += 2  # crossover is strong signal
        elif macd["crossover"] == "bearish":
            bearish_signals += 2
    
    if bb["zone"] == "oversold":
        bullish_signals += 1
    elif bb["zone"] == "overbought":
        bearish_signals += 1
    
    if vol_trend == "accumulation":
        bullish_signals += 1
    elif vol_trend == "distribution":
        bearish_signals += 1
    
    if bullish_signals > bearish_signals + 1:
        verdict = "BUY"
    elif bearish_signals > bullish_signals + 1:
        verdict = "SELL"
    else:
        verdict = "HOLD"
    
    confidence = abs(bullish_signals - bearish_signals) / max(bullish_signals + bearish_signals, 1)
    
    return {
        "verdict": verdict,
        "confidence": round(confidence * 100),
        "bullish_signals": bullish_signals,
        "bearish_signals": bearish_signals,
        "rsi": rsi,
        "macd": macd,
        "bollinger": bb,
        "support_resistance": sr,
        "volume_trend": vol_trend
    }

def interpret_analysis(analysis: dict, ticker: str, current_price: float) -> str:
    """Convert technical analysis into plain English for users"""
    if "error" in analysis:
        return f"Insufficient price history for {ticker} technical analysis."
    
    verdict = analysis["verdict"]
    confidence = analysis["confidence"]
    rsi = analysis["rsi"]
    macd = analysis["macd"]
    bb = analysis["bollinger"]
    sr = analysis["support_resistance"]
    vol_trend = analysis["volume_trend"]
    
    lines = []
    
    # RSI
    if rsi is not None:
        if rsi >= 70:
            lines.append(f"RSI {rsi:.0f} — overbought, high risk of pullback")
        elif rsi <= 30:
            lines.append(f"RSI {rsi:.0f} — oversold, potential bounce setup")
        elif rsi >= 55:
            lines.append(f"RSI {rsi:.0f} — healthy bullish momentum")
        elif rsi <= 45:
            lines.append(f"RSI {rsi:.0f} — weak momentum, bearish bias")
        else:
            lines.append(f"RSI {rsi:.0f} — neutral")
    
    # MACD
    if macd["crossover"] == "bullish":
        lines.append("MACD bullish crossover — momentum turning positive")
    elif macd["crossover"] == "bearish":
        lines.append("MACD bearish crossover — momentum turning negative")
    elif macd["macd"] is not None:
        if macd["macd"] > macd["signal"]:
            lines.append("MACD above signal line — upward momentum")
        else:
            lines.append("MACD below signal line — downward momentum")
    
    # Bollinger Bands
    if bb["zone"] == "overbought":
        lines.append(f"Price at upper Bollinger Band — stretched, avoid chasing")
    elif bb["zone"] == "oversold":
        lines.append(f"Price at lower Bollinger Band — potential entry zone")
    if bb.get("squeeze"):
        lines.append("Bollinger Band squeeze — big move incoming, direction unclear")
    
    # Support/Resistance
    if sr["support"] and sr["resistance"]:
        lines.append(
            f"Support: ₦{sr['support']:,.2f} | Resistance: ₦{sr['resistance']:,.2f}"
        )
    
    # Volume
    if vol_trend == "accumulation":
        lines.append("Volume: institutional accumulation — smart money buying")
    elif vol_trend == "distribution":
        lines.append("Volume: distribution — smart money selling")
    
    # Verdict
    verdict_text = {
        "BUY": f"Verdict: BUY — {confidence}% confidence. Entry at current levels is supported by technicals.",
        "SELL": f"Verdict: AVOID/EXIT — {confidence}% confidence. Technical setup is deteriorating.",
        "HOLD": f"Verdict: HOLD — mixed signals. Existing holders stay, new buyers wait for clearer setup."
    }
    
    analysis_text = "\n".join(lines)
    return f"{ticker} Technical Analysis\n\n{analysis_text}\n\n{verdict_text[verdict]}"