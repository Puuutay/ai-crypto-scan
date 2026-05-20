import os
import time
import requests
import ccxt
import pandas as pd
import ta

from dotenv import load_dotenv

# =========================
# LOAD ENV
# =========================

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =========================
# EXCHANGE
# =========================

exchange = ccxt.binance({
    "enableRateLimit": True
})

# =========================
# SETTINGS
# =========================

TIMEFRAME = "15m"

MIN_RR = 2.0

SCAN_INTERVAL = 60

SYMBOLS = [

    # MAJORS
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",

    # MID CAPS
    "ONDO/USDT",
    "LINK/USDT",
    "AVAX/USDT",
    "ARB/USDT",
    "OP/USDT",

    # MEME COINS
    "DOGE/USDT",
    "SHIB/USDT",
    "PEPE/USDT",
    "WIF/USDT",
    "BONK/USDT",
    "FLOKI/USDT",

    # VOLATILE
    "SUI/USDT",
    "SEI/USDT",
    "APT/USDT",
    "INJ/USDT",
    "TIA/USDT"
]

# =========================
# LOAD MARKET DATA
# =========================

def load_ohlcv(symbol, timeframe="15m", limit=300):

    ohlcv = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit
    )

    df = pd.DataFrame(
        ohlcv,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    )

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        unit="ms"
    )

    return df

# =========================
# INDICATORS
# =========================

def apply_indicators(df):

    df["ema_20"] = ta.trend.ema_indicator(
        df["close"],
        window=20
    )

    df["ema_50"] = ta.trend.ema_indicator(
        df["close"],
        window=50
    )

    df["adx"] = ta.trend.adx(
        df["high"],
        df["low"],
        df["close"]
    )

    df["rsi"] = ta.momentum.rsi(
        df["close"],
        window=14
    )

    df["atr"] = ta.volatility.average_true_range(
        df["high"],
        df["low"],
        df["close"]
    )

    df["roc"] = ta.momentum.roc(
        df["close"],
        window=5
    )

    return df

# =========================
# MARKET REGIME
# =========================

def detect_market_regime(df):

    atr = df["atr"].iloc[-1]

    price = df["close"].iloc[-1]

    atr_percent = (atr / price) * 100

    ema20 = df["ema_20"].iloc[-1]

    ema50 = df["ema_50"].iloc[-1]

    if atr_percent < 1:
        return "dead_market"

    if abs(ema20 - ema50) < price * 0.002:
        return "ranging"

    if atr_percent > 3:
        return "volatile"

    return "trending"

# =========================
# TREND ANALYSIS
# =========================

def analyze_trend(df):

    ema20 = df["ema_20"].iloc[-1]

    ema50 = df["ema_50"].iloc[-1]

    adx = df["adx"].iloc[-1]

    if ema20 > ema50:
        direction = "bullish"
    else:
        direction = "bearish"

    if adx > 30:
        strength = "strong"

    elif adx > 20:
        strength = "moderate"

    else:
        strength = "weak"

    return {
        "direction": direction,
        "strength": strength,
        "adx": round(adx, 2)
    }

# =========================
# MOMENTUM
# =========================

def analyze_momentum(df):

    roc = df["roc"].iloc[-1]

    rsi = df["rsi"].iloc[-1]

    strong = abs(roc) > 2

    return {
        "roc": round(roc, 2),
        "rsi": round(rsi, 2),
        "strong": strong
    }

# =========================
# VOLATILITY
# =========================

def analyze_volatility(df):

    atr = df["atr"].iloc[-1]

    price = df["close"].iloc[-1]

    volatility = (atr / price) * 100

    return {
        "volatility_percent": round(volatility, 2),
        "active": volatility >= 1.5
    }

# =========================
# VOLUME
# =========================

def analyze_volume(df):

    current_volume = df["volume"].iloc[-1]

    average_volume = (
        df["volume"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    relative_volume = (
        current_volume / average_volume
    )

    return {
        "relative_volume": round(relative_volume, 2),
        "strong_volume": relative_volume >= 1.5
    }

# =========================
# LIQUIDITY SWEEP
# =========================

def detect_liquidity_sweep(df):

    last = df.iloc[-1]

    body = abs(
        last["close"] - last["open"]
    )

    wick = last["high"] - max(
        last["close"],
        last["open"]
    )

    sweep = wick > body * 2

    return {
        "liquidity_sweep": sweep
    }

# =========================
# NO TRADE FILTER
# =========================

def should_skip_trade(
    momentum,
    volatility,
    volume,
    regime
):

    if not momentum["strong"]:
        return True, "Weak momentum"

    if not volatility["active"]:
        return True, "Low volatility"

    if not volume["strong_volume"]:
        return True, "Weak volume"

    if regime == "dead_market":
        return True, "Dead market"

    return False, "Valid setup"

# =========================
# RISK MANAGER
# =========================

def calculate_trade_levels(
    price,
    atr,
    direction
):

    sl_distance = atr * 1.5

    if direction == "bullish":

        stop_loss = (
            price - sl_distance
        )

        take_profit = (
            price + (
                sl_distance * MIN_RR
            )
        )

    else:

        stop_loss = (
            price + sl_distance
        )

        take_profit = (
            price - (
                sl_distance * MIN_RR
            )
        )

    return {
        "entry": round(price, 4),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "rr": MIN_RR
    }

# =========================
# TELEGRAM ALERT
# =========================

def send_telegram_alert(message):

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    requests.post(url, json=payload)

# =========================
# MAIN SCANNER
# =========================

def scan_market():

    for symbol in SYMBOLS:

        try:

            print(f"Scanning {symbol}")

            df = load_ohlcv(
                symbol,
                TIMEFRAME
            )

            df = apply_indicators(df)

            regime = detect_market_regime(df)

            trend = analyze_trend(df)

            momentum = analyze_momentum(df)

            volatility = analyze_volatility(df)

            volume = analyze_volume(df)

            liquidity = detect_liquidity_sweep(df)

            skip, reason = should_skip_trade(
                momentum,
                volatility,
                volume,
                regime
            )

            if skip:

                print(
                    f"{symbol} SKIPPED: {reason}"
                )

                continue

            price = df["close"].iloc[-1]

            atr = df["atr"].iloc[-1]

            levels = calculate_trade_levels(
                price,
                atr,
                trend["direction"]
            )

            signal_type = (
                "LONG"
                if trend["direction"] == "bullish"
                else "SHORT"
            )

            message = f'''
━━━━━━━━━━━━━━━━━━
🏆 CLEAN MARKET SIGNAL
━━━━━━━━━━━━━━━━━━

🪙 Symbol: {symbol}

📢 Signal: {signal_type}

━━━━━━━━━━━━━━━━━━
📊 Market Analysis
━━━━━━━━━━━━━━━━━━

📈 Regime: {regime}

📊 Trend Strength: {trend['strength']}

ADX: {trend['adx']}

Momentum ROC: {momentum['roc']}%

RSI: {momentum['rsi']}

Volatility: {volatility['volatility_percent']}%

Relative Volume: {volume['relative_volume']}

Liquidity Sweep: {liquidity['liquidity_sweep']}

━━━━━━━━━━━━━━━━━━
🎯 Trade Execution
━━━━━━━━━━━━━━━━━━

💰 Entry: {levels['entry']}

🛑 Stop Loss: {levels['stop_loss']}

🎯 Take Profit: {levels['take_profit']}

⚖ Risk Reward: 1:{levels['rr']}

━━━━━━━━━━━━━━━━━━
⚠ IMPORTANT
━━━━━━━━━━━━━━━━━━

Probability-based setup only.

No guaranteed outcome.

Avoid overleveraging.
'''

            print(message)

            send_telegram_alert(message)

        except Exception as e:

            print(
                f"ERROR {symbol}: {e}"
            )

# =========================
# LOOP
# =========================

if __name__ == "__main__":

    while True:

        print("Starting market scan...")

        scan_market()

        print(
            f"Sleeping {SCAN_INTERVAL} seconds..."
        )

        time.sleep(SCAN_INTERVAL)        raise Exception("Not Enough Candles")

    closes = [
        float(x["close"])
        for x in candles
    ]

    volumes = [
        float(x["volumeto"])
        for x in candles
    ]

    return closes, volumes

# =====================================
# MARKET REGIME
# =====================================

def market_regime(closes):

    sma20 = statistics.mean(closes[-20:])
    sma50 = statistics.mean(closes[-50:])

    if sma20 > sma50:
        return "TRENDING 🚀"

    elif sma20 < sma50:
        return "BEARISH 🩸"

    return "RANGING ⚖️"

# =====================================
# VOLATILITY
# =====================================

def volatility_score(closes):

    recent = closes[-20:]

    high = max(recent)
    low = min(recent)

    volatility = ((high - low) / low) * 100

    return round(volatility, 2)

# =====================================
# MOMENTUM
# =====================================

def momentum_score(closes):

    latest = closes[-1]
    old = closes[-10]

    momentum = (
        (latest - old) / old
    ) * 100

    return round(momentum, 2)

# =====================================
# TREND ALIGNMENT
# =====================================

def trend_alignment(closes):

    sma20 = statistics.mean(closes[-20:])
    sma50 = statistics.mean(closes[-50:])

    diff = abs(sma20 - sma50)

    score = min(diff * 2, 100)

    return round(score, 2)

# =====================================
# LIQUIDITY ALIGNMENT
# =====================================

def liquidity_alignment(volumes):

    avg_volume = statistics.mean(volumes[-20:])
    current_volume = volumes[-1]

    if avg_volume == 0:
        return 0

    ratio = current_volume / avg_volume

    score = min(ratio * 50, 100)

    return round(score, 2)

# =====================================
# MOMENTUM ALIGNMENT
# =====================================

def momentum_alignment(momentum):

    score = min(
        abs(momentum) * 30,
        100
    )

    return round(score, 2)

# =====================================
# RISK STABILITY
# =====================================

def risk_stability(volatility):

    score = max(
        100 - (volatility * 5),
        1
    )

    return round(score, 2)

# =====================================
# CONSENSUS ENGINE
# =====================================

def consensus_engine(
    trend,
    liquidity,
    momentum,
    risk
):

    score = (
        trend * 0.25 +
        liquidity * 0.20 +
        momentum * 0.25 +
        risk * 0.30
    )

    return round(score, 2)

# =====================================
# SIGNAL CONFLICT
# =====================================

def signal_conflict(
    trend,
    momentum,
    risk
):

    if risk < 20:
        return "HIGH"

    elif trend < 25 or momentum < 25:
        return "MODERATE"

    return "LOW"

# =====================================
# NO TRADE FILTER
# =====================================

def no_trade_filter(
    volatility,
    consensus,
    conflict
):

    if volatility > 12:
        return True

    if consensus < 35:
        return True

    if conflict == "HIGH":
        return True

    return False

# =====================================
# SIGNAL ENGINE
# =====================================

def signal_engine(
    regime,
    momentum,
    consensus
):

    if (
        "TRENDING" in regime
        and momentum > 0
        and consensus >= 40
    ):
        return "BUY 🚀"

    elif (
        "BEARISH" in regime
        and momentum < 0
        and consensus >= 40
    ):
        return "SELL 🩸"

    # FALLBACK
    if momentum > 0:
        return "BUY 🚀"

    return "SELL 🩸"

# =====================================
# EXECUTION ZONES
# =====================================

def execution_zones(
    current_price,
    volatility,
    signal
):

    move = current_price * (
        volatility / 100
    )

    if move <= 0:
        move = current_price * 0.01

    if "BUY" in signal:

        entry_low = round(
            current_price * 0.997,
            2
        )

        entry_high = round(
            current_price * 1.002,
            2
        )

        stop_loss = round(
            current_price - (move * 0.8),
            2
        )

        tp1 = round(
            current_price + (move * 1.5),
            2
        )

        tp2 = round(
            current_price + (move * 3),
            2
        )

    else:

        entry_low = round(
            current_price * 0.998,
            2
        )

        entry_high = round(
            current_price * 1.003,
            2
        )

        stop_loss = round(
            current_price + (move * 0.8),
            2
        )

        tp1 = round(
            current_price - (move * 1.5),
            2
        )

        tp2 = round(
            current_price - (move * 3),
            2
        )

    rr = round(
        abs(tp2 - current_price)
        /
        max(abs(current_price - stop_loss), 1),
        2
    )

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "sl": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr
    }

# =====================================
# MAIN ANALYSIS
# =====================================

def analyze():

    best_setup = None

    for symbol in SYMBOLS:

        try:

            closes, volumes = get_price_data(symbol)

            price = closes[-1]

            regime = market_regime(closes)

            volatility = volatility_score(closes)

            momentum = momentum_score(closes)

            trend_score = trend_alignment(closes)

            liquidity_score = liquidity_alignment(volumes)

            momentum_score_value = momentum_alignment(
                momentum
            )

            risk_score = risk_stability(
                volatility
            )

            consensus = consensus_engine(
                trend_score,
                liquidity_score,
                momentum_score_value,
                risk_score
            )

            conflict = signal_conflict(
                trend_score,
                momentum_score_value,
                risk_score
            )

            blocked = no_trade_filter(
                volatility,
                consensus,
                conflict
            )

            if blocked:
                continue

            signal = signal_engine(
                regime,
                momentum,
                consensus
            )

            if (
                best_setup is None
                or
                consensus > best_setup["consensus"]
            ):

                best_setup = {
                    "symbol": symbol,
                    "price": price,
                    "signal": signal,
                    "consensus": consensus,
                    "momentum": momentum,
                    "volatility": volatility,
                    "regime": regime,
                    "risk": risk_score
                }

        except Exception as e:

            print(f"ERROR {symbol}: {e}")

    # =====================================
    # NO SETUP
    # =====================================

    if not best_setup:

        report = """
━━━━━━━━━━━━━━━━━━
⚠️ MARKET STATUS
━━━━━━━━━━━━━━━━━━

No valid setup found.

Market conditions weak.
━━━━━━━━━━━━━━━━━━
"""

        print(report)

        send_telegram(report)

        return

    # =====================================
    # EXECUTION
    # =====================================

    zones = execution_zones(
        best_setup["price"],
        best_setup["volatility"],
        best_setup["signal"]
    )

    # =====================================
    # FINAL REPORT
    # =====================================

    report = f"""
━━━━━━━━━━━━━━━━━━
🏆 TOP MARKET OPPORTUNITY
━━━━━━━━━━━━━━━━━━

🪙 Symbol:
{best_setup['symbol']}USDT

💰 Current Price:
{best_setup['price']}

📢 Signal:
{best_setup['signal']}

━━━━━━━━━━━━━━━━━━
🎯 Trade Execution
━━━━━━━━━━━━━━━━━━

Entry Zone:
{zones['entry_low']} - {zones['entry_high']}

Stop Loss:
{zones['sl']}

Take Profit 1:
{zones['tp1']}

Take Profit 2:
{zones['tp2']}

Risk : Reward
1 : {zones['rr']}

━━━━━━━━━━━━━━━━━━
📊 Market Analysis
━━━━━━━━━━━━━━━━━━

Regime:
{best_setup['regime']}

Consensus Score:
{best_setup['consensus']}%

Momentum:
{best_setup['momentum']}%

Volatility:
{best_setup['volatility']}%

Risk Stability:
{best_setup['risk']}%

━━━━━━━━━━━━━━━━━━
🕒 Time
━━━━━━━━━━━━━━━━━━

{datetime.utcnow()} UTC
━━━━━━━━━━━━━━━━━━
"""

    print(report)

    send_telegram(report)

# =====================================
# START
# =====================================

if __name__ == "__main__":
    analyze()
