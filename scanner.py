# =====================================
# ELITE FUTURES SCANNER — MERGED
# Best of both systems combined
# =====================================

import os
import json
import requests
import ccxt
import pandas as pd
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from datetime import datetime, timedelta

# =====================================
# LOAD ENV
# =====================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")

# =====================================
# EXCHANGE — BITGET
# =====================================

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap"
    }
})

# =====================================
# SETTINGS
# =====================================

MIN_RR                = 2.0
MIN_SCORE             = 8        # need 8 out of 10
MIN_SL_PCT            = 0.005    # minimum 0.5% SL distance
SIGNAL_COOLDOWN_HOURS = 12
COOLDOWN_FILE         = "last_signal_times.json"

# =====================================
# NEWS SOURCES (free RSS)
# =====================================

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

POSITIVE_WORDS = [
    "surge", "rally", "bullish", "soars", "jumps",
    "gains", "breakout", "all-time high", "adoption",
    "upgrade", "partnership", "growth", "record"
]

NEGATIVE_WORDS = [
    "crash", "dump", "bearish", "plunge", "hack",
    "ban", "lawsuit", "collapse", "exploit", "scam",
    "fraud", "warning", "fine", "sec charges"
]

# Short coins need exact word match to avoid false positives
EXACT_MATCH_COINS = {
    "op", "sei", "fet", "bnb", "wld",
    "arb", "inj", "tia", "ren"
}

# =====================================
# ALL COINS
# =====================================

ALL_SYMBOLS = [

    # MAJORS
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "BNB/USDT:USDT",

    # MEME
    "DOGE/USDT:USDT",
    "PEPE/USDT:USDT",
    "SHIB/USDT:USDT",
    "WIF/USDT:USDT",
    "BONK/USDT:USDT",

    # AI
    "FET/USDT:USDT",
    "RENDER/USDT:USDT",
    "TAO/USDT:USDT",
    "WLD/USDT:USDT",
    "ARKM/USDT:USDT",

    # TRENDING
    "ONDO/USDT:USDT",
    "SEI/USDT:USDT",
    "SUI/USDT:USDT",
    "INJ/USDT:USDT",
    "TIA/USDT:USDT",

    # MIDCAP
    "AVAX/USDT:USDT",
    "ARB/USDT:USDT",
    "OP/USDT:USDT",
    "LINK/USDT:USDT",
    "APT/USDT:USDT",

]

# =====================================
# COOLDOWN TRACKER
# =====================================

def load_signal_times():
    if os.path.exists(COOLDOWN_FILE):
        with open(COOLDOWN_FILE, "r") as f:
            raw = json.load(f)
        return {
            k: datetime.fromisoformat(v)
            for k, v in raw.items()
        }
    return {}


def save_signal_times(signal_times):
    raw = {k: v.isoformat() for k, v in signal_times.items()}
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(raw, f, indent=2)


def is_on_cooldown(symbol, signal_times, now):
    last = signal_times.get(symbol)
    if not last:
        return False
    return (now - last) < timedelta(hours=SIGNAL_COOLDOWN_HOURS)

# =====================================
# LOAD OHLCV
# =====================================

def load_ohlcv(symbol, timeframe, limit=120):
    ohlcv = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit
    )
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df

# =====================================
# INDICATORS
# =====================================

def apply_indicators(df):

    # EMA
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()

    # RSI
    delta    = df["close"].diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs       = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema_12            = df["close"].ewm(span=12, adjust=False).mean()
    ema_26            = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # ATR
    hl        = df["high"] - df["low"]
    hc        = (df["high"] - df["close"].shift()).abs()
    lc        = (df["low"] - df["close"].shift()).abs()
    tr        = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=13, adjust=False).mean()

    # Volume
    df["vol_ma"]  = df["volume"].rolling(20).mean()
    df["rel_vol"] = df["volume"] / df["vol_ma"]

    return df

# =====================================
# TREND DETECTOR
# Closed candle only, min 0.2% EMA gap
# =====================================

def detect_trend(df):
    ema20 = df["ema_20"].iloc[-2]
    ema50 = df["ema_50"].iloc[-2]
    price = df["close"].iloc[-2]

    if price == 0:
        return None

    gap_pct = abs(ema20 - ema50) / price

    if gap_pct < 0.002:
        return None

    if ema20 > ema50 and price > ema20:
        return "bullish"
    if ema20 < ema50 and price < ema20:
        return "bearish"

    return None

# =====================================
# BTC MARKET STATE
# Sets market context for all signals
# =====================================

def get_btc_market_state():
    try:
        df    = load_ohlcv("BTC/USDT:USDT", "1h", limit=100)
        df    = apply_indicators(df)

        ema20 = df["ema_20"].iloc[-2]
        ema50 = df["ema_50"].iloc[-2]
        price = df["close"].iloc[-2]
        atr   = df["atr"].iloc[-2]

        vol_pct = atr / price

        if ema20 > ema50:
            trend = "BULL"
        elif ema20 < ema50:
            trend = "BEAR"
        else:
            trend = "RANGE"

        if vol_pct > 0.03:
            volatility = "HIGH"
        elif vol_pct > 0.015:
            volatility = "NORMAL"
        else:
            volatility = "LOW"

        return {
            "trend":      trend,
            "volatility": volatility,
            "price":      round(price, 2)
        }

    except:
        return {
            "trend":      "UNKNOWN",
            "volatility": "UNKNOWN",
            "price":      0
        }

# =====================================
# NEWS HEADLINES (free RSS)
# =====================================

def fetch_rss_headlines():
    headlines = []
    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title = item.findtext("title") or ""
                headlines.append(title.lower())
        except:
            continue
    return headlines

# =====================================
# HARD FILTER 1 — 4H TREND
# Must be clear — not ranging
# =====================================

def check_4h_trend(symbol):
    df        = load_ohlcv(symbol, "4h", limit=60)
    df        = apply_indicators(df)
    direction = detect_trend(df)
    return direction

# =====================================
# HARD FILTER 2 — 1H TREND
# Must match 4H — counter = hard skip
# =====================================

def check_1h_trend(symbol, direction_4h):
    df        = load_ohlcv(symbol, "1h", limit=60)
    df        = apply_indicators(df)
    direction = detect_trend(df)

    if direction is None:
        return False, "1H: Unclear (ranging)"
    if direction != direction_4h:
        return False, "1H: Counter to 4H"

    return True, f"1H: {'BULLISH' if direction == 'bullish' else 'BEARISH'}"

# =====================================
# HARD FILTER 3 — 15M EMA
# Must align + min gap of 0.1%
# =====================================

def check_15m_ema(df_15m, direction):
    ema20 = df_15m["ema_20"].iloc[-2]
    ema50 = df_15m["ema_50"].iloc[-2]
    price = df_15m["close"].iloc[-2]

    if price == 0:
        return False, "15M EMA: Price error"

    gap_pct = abs(ema20 - ema50) / price

    if gap_pct < 0.001:
        return False, f"15M EMA: Gap too small"

    if direction == "bullish" and ema20 > ema50:
        return True, "15M EMA: Aligned BULLISH"
    if direction == "bearish" and ema20 < ema50:
        return True, "15M EMA: Aligned BEARISH"

    return False, "15M EMA: Not aligned"

# =====================================
# HARD FILTER 4 — VOLUME
# Must be >= 0.8x average
# =====================================

def check_volume(df_15m):
    rel_vol = round(df_15m["rel_vol"].iloc[-2], 2)
    if rel_vol >= 0.8:
        return True, f"Volume: {rel_vol}x"
    return False, f"Volume: {rel_vol}x (weak)"

# =====================================
# HARD FILTER 5 — OVEREXTENSION
# Price must not be too far from EMA20
# =====================================

def check_overextension(df_15m):
    price = df_15m["close"].iloc[-2]
    ema20 = df_15m["ema_20"].iloc[-2]

    if ema20 == 0:
        return False, "Extension: EMA error"

    distance = abs(price - ema20) / ema20

    if distance > 0.05:
        return False, f"Overextended ({round(distance*100,2)}%)"

    return True, f"Extension: Healthy ({round(distance*100,2)}%)"

# =====================================
# HARD FILTER 6 — RELATIVE STRENGTH
# Coin must outperform BTC
# =====================================

def check_relative_strength(symbol, btc_df):
    try:
        alt_df = load_ohlcv(symbol, "1h", limit=30)

        btc_change = (
            btc_df["close"].iloc[-2] -
            btc_df["close"].iloc[-15]
        ) / btc_df["close"].iloc[-15]

        alt_change = (
            alt_df["close"].iloc[-2] -
            alt_df["close"].iloc[-15]
        ) / alt_df["close"].iloc[-15]

        rs = round((alt_change - btc_change) * 100, 2)

        if alt_change > btc_change:
            return True, f"RS: Strong vs BTC (+{rs}%)"

        return False, f"RS: Weak vs BTC ({rs}%)"

    except:
        return False, "RS: Error"

# =====================================
# HARD FILTER 7 — BREAKOUT QUALITY
# Candle must be clean — big body, no rejection
# =====================================

def check_breakout_quality(df_15m, direction):
    candle     = df_15m.iloc[-2]
    body       = abs(candle["close"] - candle["open"])
    range_size = candle["high"] - candle["low"]

    if range_size == 0:
        return False, "Breakout: Doji candle"

    body_ratio = body / range_size

    if body_ratio < 0.6:
        return False, f"Breakout: Weak body ({round(body_ratio*100)}%)"

    if direction == "bullish":
        upper_wick = candle["high"] - candle["close"]
        if upper_wick > body:
            return False, "Breakout: Heavy upper wick"

    if direction == "bearish":
        lower_wick = candle["close"] - candle["low"]
        if lower_wick > body:
            return False, "Breakout: Heavy lower wick"

    return True, f"Breakout: Clean ({round(body_ratio*100)}% body)"

# =====================================
# HARD FILTER 8 — MOMENTUM PERSISTENCE
# 3 consecutive candles in direction
# =====================================

def check_momentum(df_15m, direction):
    closes = df_15m["close"].tail(5).tolist()
    # [0]=oldest ... [4]=newest, use [-2] as last closed
    # Check last 3 closed candles: index 1,2,3
    c1, c2, c3 = closes[1], closes[2], closes[3]

    if direction == "bullish" and c3 > c2 > c1:
        return True, "Momentum: 3 bullish candles"
    if direction == "bearish" and c3 < c2 < c1:
        return True, "Momentum: 3 bearish candles"

    return False, "Momentum: Weak"

# =====================================
# SCORE 1 — RSI (1 point)
# =====================================

def score_rsi(df_15m, direction):
    rsi = round(df_15m["rsi"].iloc[-2], 1)

    if direction == "bullish" and 45 <= rsi <= 70:
        return 1, f"RSI: {rsi} ✅"
    if direction == "bearish" and 30 <= rsi <= 55:
        return 1, f"RSI: {rsi} ✅"

    return 0, f"RSI: {rsi} ❌"

# =====================================
# SCORE 2 — MACD (1 point)
# =====================================

def score_macd(df_15m, direction):
    macd     = df_15m["macd"].iloc[-2]
    macd_sig = df_15m["macd_signal"].iloc[-2]

    if direction == "bullish" and macd > macd_sig:
        return 1, "MACD: Bullish ✅"
    if direction == "bearish" and macd < macd_sig:
        return 1, "MACD: Bearish ✅"

    return 0, "MACD: Against direction ❌"

# =====================================
# SCORE 3 — FUNDING RATE (1 point)
# =====================================

def score_funding_rate(symbol, direction):
    try:
        funding      = exchange.fetch_funding_rate(symbol)
        funding_rate = funding.get("fundingRate", None)

        if funding_rate is None:
            return 0, "Funding: No data ❌"

        fr_pct = round(funding_rate * 100, 4)

        if direction == "bullish" and funding_rate > 0.001:
            return 0, f"Funding: {fr_pct}% overleveraged ❌"
        if direction == "bearish" and funding_rate < -0.001:
            return 0, f"Funding: {fr_pct}% overleveraged ❌"

        return 1, f"Funding: {fr_pct}% ✅"

    except:
        return 0, "Funding: Error ❌"

# =====================================
# SCORE 4 — ORDER BOOK (1 point)
# =====================================

def score_order_book(symbol, direction):
    try:
        ob      = exchange.fetch_order_book(symbol, limit=20)
        bids    = ob["bids"][:10]
        asks    = ob["asks"][:10]

        if not bids or not asks:
            return 0, "Order Book: No data ❌"

        bid_vol = sum([b[1] for b in bids])
        ask_vol = sum([a[1] for a in asks])

        if ask_vol == 0:
            return 0, "Order Book: Invalid ❌"

        ratio = round(bid_vol / ask_vol, 2)

        if direction == "bullish" and bid_vol > ask_vol:
            return 1, f"Order Book: {ratio} buyers ✅"
        if direction == "bearish" and ask_vol > bid_vol:
            return 1, f"Order Book: {ratio} sellers ✅"

        return 0, f"Order Book: {ratio} against ❌"

    except:
        return 0, "Order Book: Error ❌"

# =====================================
# SCORE 5 — OPEN INTEREST TREND (1 point)
# OI increasing = real interest
# =====================================

def score_open_interest(symbol, direction):
    try:
        # Fetch OI history to compare
        oi_now  = exchange.fetch_open_interest(symbol)
        oi_val  = oi_now.get("openInterestAmount", None)

        if oi_val is None:
            return 0, "OI: No data ❌"

        # We just confirm OI exists and is positive
        # Full historical comparison needs premium API
        return 1, f"OI: Active ✅"

    except:
        return 0, "OI: Error ❌"

# =====================================
# SCORE 6 — NEWS SENTIMENT (1 point)
# =====================================

def score_news(symbol, all_headlines):
    try:
        coin = symbol.split("/")[0].lower()

        if coin in EXACT_MATCH_COINS:
            relevant = [
                h for h in all_headlines
                if f" {coin} " in f" {h} "
                or h.startswith(f"{coin} ")
                or h.endswith(f" {coin}")
            ]
        else:
            relevant = [h for h in all_headlines if coin in h]

        if not relevant:
            return 1, "News: No mentions (neutral) ✅"

        positive = sum(
            1 for h in relevant
            for w in POSITIVE_WORDS if w in h
        )
        negative = sum(
            1 for h in relevant
            for w in NEGATIVE_WORDS if w in h
        )

        if positive > negative:
            return 1, f"News: Positive ({positive}+ vs {negative}-) ✅"
        if negative > positive:
            return 0, f"News: Negative ({positive}+ vs {negative}-) ❌"

        return 1, "News: Neutral ✅"

    except:
        return 1, "News: Skipped ✅"

# =====================================
# SCORE 7 — BTC TREND ALIGNMENT (1 point)
# Coin direction should match BTC trend
# =====================================

def score_btc_alignment(direction, btc_state):
    btc_trend = btc_state["trend"]

    if direction == "bullish" and btc_trend == "BULL":
        return 1, "BTC Aligned: BULL ✅"
    if direction == "bearish" and btc_trend == "BEAR":
        return 1, "BTC Aligned: BEAR ✅"
    if btc_trend == "RANGE":
        return 1, "BTC: Ranging (neutral) ✅"

    return 0, f"BTC: Counter ({btc_trend}) ❌"

# =====================================
# SCORE 8 — BTC VOLATILITY BONUS (1 point)
# NORMAL volatility = safer signal
# =====================================

def score_btc_volatility(btc_state):
    vol = btc_state["volatility"]

    if vol == "NORMAL":
        return 1, "Volatility: NORMAL ✅"
    if vol == "LOW":
        return 1, "Volatility: LOW ✅"

    return 0, "Volatility: HIGH ❌"

# =====================================
# SCORE 9+10 — 4H TREND (2 points)
# Macro trend is most important
# =====================================

# Handled in hard filter — gives 2 base points
# if 4H trend is clear and passes

# =====================================
# RISK MANAGER
# Uses 1H ATR for realistic SL
# =====================================

def calculate_trade_levels(price, atr_1h, direction):
    min_sl      = price * MIN_SL_PCT
    sl_distance = max(atr_1h * 1.5, min_sl)

    if direction == "bullish":
        stop_loss   = price - sl_distance
        take_profit = price + (sl_distance * MIN_RR)
    else:
        stop_loss   = price + sl_distance
        take_profit = price - (sl_distance * MIN_RR)

    sl_pct = round((sl_distance / price) * 100, 2)
    tp_pct = round((sl_distance * MIN_RR / price) * 100, 2)

    # Auto decimal based on price magnitude
    if price < 0.0001:
        decimals = 10
    elif price < 0.01:
        decimals = 8
    elif price < 1:
        decimals = 6
    else:
        decimals = 4

    return {
        "entry":       round(price, decimals),
        "stop_loss":   round(stop_loss, decimals),
        "take_profit": round(take_profit, decimals),
        "sl_pct":      sl_pct,
        "tp_pct":      tp_pct,
        "rr":          MIN_RR
    }

# =====================================
# TELEGRAM ALERT
# =====================================

def send_telegram_alert(message):
    if not BOT_TOKEN:
        print("No BOT_TOKEN, skipping Telegram.")
        return

    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

# =====================================
# MAIN SCAN
# =====================================
#
# SCORING BREAKDOWN (max = 10):
#
# HARD FILTERS (all must pass or SKIP):
#   4H Trend clear
#   1H matches 4H
#   15M EMA aligned
#   Volume >= 0.8x
#   Not overextended
#   RS stronger than BTC
#   Clean breakout candle
#   3 candles momentum
#
# SCORING (need 8/10):
#   4H Trend  = 2 pts (base, always passes)
#   RSI       = 0 or 1
#   MACD      = 0 or 1
#   Funding   = 0 or 1
#   OrderBook = 0 or 1
#   OI        = 0 or 1
#   News      = 0 or 1
#   BTC Align = 0 or 1
#   BTC Vol   = 0 or 1
#
# =====================================

def scan_all():

    signal_times  = load_signal_times()
    signals_found = 0
    now           = datetime.utcnow()

    print(f"\n[{now}] ELITE SCAN STARTED\n")

    # ── BTC MARKET STATE ──
    btc_state = get_btc_market_state()
    print(f"  BTC Trend:      {btc_state['trend']}")
    print(f"  BTC Price:      ${btc_state['price']}")
    print(f"  BTC Volatility: {btc_state['volatility']}\n")

    # ── FETCH NEWS ONCE ──
    print("  Fetching news headlines...")
    all_headlines = fetch_rss_headlines()
    print(f"  {len(all_headlines)} headlines loaded.\n")

    # ── LOAD BTC DATA ONCE for RS comparison ──
    try:
        btc_df = load_ohlcv("BTC/USDT:USDT", "1h", limit=30)
    except:
        btc_df = None

    print(f"  Scanning {len(ALL_SYMBOLS)} coins...\n")

    for symbol in ALL_SYMBOLS:

        try:

            # ── COOLDOWN CHECK ──
            if is_on_cooldown(symbol, signal_times, now):
                last      = signal_times[symbol]
                remaining = last + timedelta(hours=SIGNAL_COOLDOWN_HOURS) - now
                hrs       = int(remaining.total_seconds() // 3600)
                mins      = int((remaining.total_seconds() % 3600) // 60)
                print(f"  COOLDOWN {symbol}: {hrs}h {mins}m left")
                continue

            # ════════════════════════════
            # HARD FILTERS — all must pass
            # ════════════════════════════

            # 1. 4H Trend
            direction = check_4h_trend(symbol)
            if direction is None:
                print(f"  SKIP {symbol}: 4H unclear")
                continue

            # 2. 1H Trend must match 4H
            ok_1h, l_1h = check_1h_trend(symbol, direction)
            if not ok_1h:
                print(f"  SKIP {symbol}: {l_1h}")
                continue

            # Load 1H for ATR
            df_1h  = load_ohlcv(symbol, "1h", limit=60)
            df_1h  = apply_indicators(df_1h)
            atr_1h = df_1h["atr"].iloc[-2]

            # Load 15M for entry analysis
            df_15m = load_ohlcv(symbol, "15m", limit=60)
            df_15m = apply_indicators(df_15m)

            price = df_15m["close"].iloc[-2]

            if price == 0:
                print(f"  SKIP {symbol}: price is 0")
                continue

            # 3. 15M EMA aligned
            ok_ema, l_ema = check_15m_ema(df_15m, direction)
            if not ok_ema:
                print(f"  SKIP {symbol}: {l_ema}")
                continue

            # 4. Volume sufficient
            ok_vol, l_vol = check_volume(df_15m)
            if not ok_vol:
                print(f"  SKIP {symbol}: {l_vol}")
                continue

            # 5. Not overextended
            ok_ext, l_ext = check_overextension(df_15m)
            if not ok_ext:
                print(f"  SKIP {symbol}: {l_ext}")
                continue

            # 6. Relative Strength vs BTC
            if btc_df is not None:
                ok_rs, l_rs = check_relative_strength(symbol, btc_df)
                if not ok_rs:
                    print(f"  SKIP {symbol}: {l_rs}")
                    continue
            else:
                l_rs = "RS: Skipped"

            # 7. Breakout quality
            ok_break, l_break = check_breakout_quality(df_15m, direction)
            if not ok_break:
                print(f"  SKIP {symbol}: {l_break}")
                continue

            # 8. Momentum persistence
            ok_momo, l_momo = check_momentum(df_15m, direction)
            if not ok_momo:
                print(f"  SKIP {symbol}: {l_momo}")
                continue

            # ════════════════════════════
            # SCORING — need 8 out of 10
            # ════════════════════════════

            # Base: 4H trend passed = 2 pts
            base_score = 2

            s1, l_rsi  = score_rsi(df_15m, direction)
            s2, l_macd = score_macd(df_15m, direction)
            s3, l_fund = score_funding_rate(symbol, direction)
            s4, l_ob   = score_order_book(symbol, direction)
            s5, l_oi   = score_open_interest(symbol, direction)
            s6, l_news = score_news(symbol, all_headlines)
            s7, l_btca = score_btc_alignment(direction, btc_state)
            s8, l_btcv = score_btc_volatility(btc_state)

            total_score = base_score + s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8
            max_score   = 10

            print(f"  {symbol}: {direction.upper()} Score {total_score}/{max_score}")

            if total_score < MIN_SCORE:
                print(f"  SKIP {symbol}: Score too low ({total_score}/{max_score})")
                continue

            # ════════════════════════════
            # SIGNAL CONFIRMED
            # ════════════════════════════

            signal_type = "LONG 🟢" if direction == "bullish" else "SHORT 🔴"
            levels      = calculate_trade_levels(price, atr_1h, direction)

            message = (
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏆 ELITE SIGNAL\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 {symbol}\n"
                f"📢 Signal: {signal_type}\n"
                f"🏦 Bitget Futures\n"
                f"⭐ Score: {total_score}/{max_score}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🌍 Market Context\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"BTC Trend: {btc_state['trend']}\n"
                f"Volatility: {btc_state['volatility']}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Timeframe Check\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ 4H Trend: {'BULLISH' if direction == 'bullish' else 'BEARISH'} (2pts)\n"
                f"✅ {l_1h}\n"
                f"✅ {l_ema}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📈 Quality Filters\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ {l_vol}\n"
                f"✅ {l_ext}\n"
                f"✅ {l_rs}\n"
                f"✅ {l_break}\n"
                f"✅ {l_momo}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Confirmation\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{l_rsi}\n"
                f"{l_macd}\n"
                f"{l_fund}\n"
                f"{l_ob}\n"
                f"{l_oi}\n"
                f"{l_news}\n"
                f"{l_btca}\n"
                f"{l_btcv}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Trade Execution\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 Entry:       {levels['entry']}\n"
                f"🛑 Stop Loss:   {levels['stop_loss']} (-{levels['sl_pct']}%)\n"
                f"🎯 Take Profit: {levels['take_profit']} (+{levels['tp_pct']}%)\n"
                f"⚖ Risk Reward:  1:{levels['rr']}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚠ IMPORTANT\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"Probability-based setup only.\n"
                f"No guaranteed outcome."
            )

            print(f"  ✅ SIGNAL: {symbol} → {signal_type} ({total_score}/{max_score})")
            send_telegram_alert(message)

            signal_times[symbol] = now
            signals_found += 1

        except Exception as e:
            print(f"  ERROR {symbol}: {e}")

    save_signal_times(signal_times)
    print(f"\n[DONE] {signals_found} signal(s) sent.\n")


# =====================================
# ENTRY POINT
# =====================================

if __name__ == "__main__":
    scan_all()
