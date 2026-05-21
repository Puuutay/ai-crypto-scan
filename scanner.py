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
SIGNAL_COOLDOWN_HOURS = 12
COOLDOWN_FILE         = "last_signal_times.json"
MIN_SCORE             = 6   # minimum out of 8

# =====================================
# NEWS SOURCES (free RSS)
# =====================================

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

POSITIVE_WORDS = [
    "surge", "rally", "bullish", "soars", "jumps",
    "gains", "rises", "pump", "breakout", "ath",
    "all-time high", "buy", "adoption", "upgrade",
    "partnership", "launch", "growth", "record"
]

NEGATIVE_WORDS = [
    "crash", "dump", "bearish", "plunge", "drops",
    "falls", "sell", "fear", "hack", "ban", "lawsuit",
    "sec", "fine", "warning", "risk", "collapse",
    "exploit", "scam", "fraud", "loss", "down"
]

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
    last_time = signal_times.get(symbol)
    if not last_time:
        return False
    return (now - last_time) < timedelta(hours=SIGNAL_COOLDOWN_HOURS)

# =====================================
# LOAD OHLCV
# =====================================

def load_ohlcv(symbol, timeframe, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
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
# SCORE 1 — 1H EMA TREND (2 points)
# =====================================

def score_1h_trend(symbol):
    try:
        df    = load_ohlcv(symbol, "1h", limit=60)
        df    = apply_indicators(df)
        ema20 = df["ema_20"].iloc[-1]
        ema50 = df["ema_50"].iloc[-1]
        price = df["close"].iloc[-1]

        if ema20 > ema50 and price > ema20:
            return "bullish", 2, "1H Trend: BULLISH"
        if ema20 < ema50 and price < ema20:
            return "bearish", 2, "1H Trend: BEARISH"

        return None, 0, "1H Trend: UNCLEAR"

    except Exception as e:
        return None, 0, f"1H Trend: ERROR"

# =====================================
# SCORE 2 — 15M EMA (1 point)
# =====================================

def score_15m_ema(df_15m, direction):
    ema20 = df_15m["ema_20"].iloc[-1]
    ema50 = df_15m["ema_50"].iloc[-1]

    if direction == "bullish" and ema20 > ema50:
        return 1, "15M EMA: Aligned BULLISH"
    if direction == "bearish" and ema20 < ema50:
        return 1, "15M EMA: Aligned BEARISH"

    return 0, "15M EMA: Not aligned"

# =====================================
# SCORE 3 — RSI (1 point)
# =====================================

def score_rsi(df_15m, direction):
    rsi = round(df_15m["rsi"].iloc[-1], 1)

    if direction == "bullish" and 45 <= rsi <= 70:
        return 1, f"RSI: {rsi} (healthy bullish)"
    if direction == "bearish" and 30 <= rsi <= 55:
        return 1, f"RSI: {rsi} (healthy bearish)"

    return 0, f"RSI: {rsi} (out of range)"

# =====================================
# SCORE 4 — MACD (1 point)
# =====================================

def score_macd(df_15m, direction):
    macd     = df_15m["macd"].iloc[-1]
    macd_sig = df_15m["macd_signal"].iloc[-1]

    if direction == "bullish" and macd > macd_sig:
        return 1, "MACD: Bullish"
    if direction == "bearish" and macd < macd_sig:
        return 1, "MACD: Bearish"

    return 0, "MACD: Against direction"

# =====================================
# SCORE 5 — VOLUME (1 point)
# =====================================

def score_volume(df_15m):
    rel_vol = round(df_15m["rel_vol"].iloc[-1], 2)

    if rel_vol >= 0.8:
        return 1, f"Volume: {rel_vol}x (sufficient)"

    return 0, f"Volume: {rel_vol}x (weak)"

# =====================================
# SCORE 6 — FUNDING RATE (1 point)
# =====================================

def score_funding_rate(symbol, direction):
    try:
        funding      = exchange.fetch_funding_rate(symbol)
        funding_rate = funding.get("fundingRate", 0)
        fr_pct       = round(funding_rate * 100, 4)

        if direction == "bullish" and funding_rate > 0.001:
            return 0, f"Funding: {fr_pct}% (overleveraged longs)"
        if direction == "bearish" and funding_rate < -0.001:
            return 0, f"Funding: {fr_pct}% (overleveraged shorts)"

        return 1, f"Funding: {fr_pct}% (favorable)"

    except:
        return 1, "Funding: N/A (skipped)"

# =====================================
# SCORE 7 — ORDER BOOK (1 point)
# =====================================

def score_order_book(symbol, direction):
    try:
        ob      = exchange.fetch_order_book(symbol, limit=20)
        bids    = ob["bids"][:10]
        asks    = ob["asks"][:10]
        bid_vol = sum([b[1] for b in bids])
        ask_vol = sum([a[1] for a in asks])
        ratio   = round(bid_vol / ask_vol if ask_vol > 0 else 1, 2)

        if direction == "bullish" and bid_vol > ask_vol:
            return 1, f"Order Book: {ratio} (buyers dominate)"
        if direction == "bearish" and ask_vol > bid_vol:
            return 1, f"Order Book: {ratio} (sellers dominate)"

        return 0, f"Order Book: {ratio} (against direction)"

    except:
        return 1, "Order Book: N/A (skipped)"

# =====================================
# SCORE 8 — NEWS SENTIMENT via RSS (1 point)
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


def score_news(symbol, all_headlines):
    try:
        coin = symbol.split("/")[0].lower()

        # Filter headlines mentioning this coin
        relevant = [h for h in all_headlines if coin in h]

        if not relevant:
            return 1, "News: No mentions (neutral)"

        positive = sum(
            1 for h in relevant
            for w in POSITIVE_WORDS if w in h
        )
        negative = sum(
            1 for h in relevant
            for w in NEGATIVE_WORDS if w in h
        )

        if positive > negative:
            return 1, f"News: Positive ({positive}+ vs {negative}-)"
        if negative > positive:
            return 0, f"News: Negative ({positive}+ vs {negative}-)"

        return 1, f"News: Neutral ({positive}+ vs {negative}-)"

    except:
        return 1, "News: N/A (skipped)"

# =====================================
# RISK MANAGER
# =====================================

def calculate_trade_levels(price, atr, direction):
    sl_distance = atr * 1.5

    if direction == "bullish":
        stop_loss   = price - sl_distance
        take_profit = price + (sl_distance * MIN_RR)
    else:
        stop_loss   = price + sl_distance
        take_profit = price - (sl_distance * MIN_RR)

    return {
        "entry":       round(price, 4),
        "stop_loss":   round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "rr":          MIN_RR
    }

# =====================================
# TELEGRAM ALERT
# =====================================

def send_telegram_alert(message):
    if not BOT_TOKEN:
        print("No BOT_TOKEN found, skipping Telegram.")
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

def scan_all():

    signal_times  = load_signal_times()
    signals_found = 0
    now           = datetime.utcnow()

    print(f"\n[{now}] Scanning {len(ALL_SYMBOLS)} coins on Bitget...\n")

    # Fetch RSS headlines once for all coins
    print("  Fetching news headlines...")
    all_headlines = fetch_rss_headlines()
    print(f"  {len(all_headlines)} headlines loaded.\n")

    for symbol in ALL_SYMBOLS:

        try:

            # Check cooldown
            if is_on_cooldown(symbol, signal_times, now):
                last      = signal_times[symbol]
                remaining = last + timedelta(hours=SIGNAL_COOLDOWN_HOURS) - now
                hrs       = int(remaining.total_seconds() // 3600)
                mins      = int((remaining.total_seconds() % 3600) // 60)
                print(f"  COOLDOWN {symbol}: {hrs}h {mins}m left")
                continue

            # ── SCORE 1: 1H Trend (2 pts) ──
            direction, s1, l1 = score_1h_trend(symbol)

            if direction is None:
                print(f"  SKIP {symbol}: {l1}")
                continue

            # Load 15M data once
            df_15m = load_ohlcv(symbol, "15m", limit=60)
            df_15m = apply_indicators(df_15m)

            price = df_15m["close"].iloc[-1]
            atr   = df_15m["atr"].iloc[-1]

            # ── SCORE 2: 15M EMA (1 pt) ──
            s2, l2 = score_15m_ema(df_15m, direction)

            # ── SCORE 3: RSI (1 pt) ──
            s3, l3 = score_rsi(df_15m, direction)

            # ── SCORE 4: MACD (1 pt) ──
            s4, l4 = score_macd(df_15m, direction)

            # ── SCORE 5: Volume (1 pt) ──
            s5, l5 = score_volume(df_15m)

            # ── SCORE 6: Funding Rate (1 pt) ──
            s6, l6 = score_funding_rate(symbol, direction)

            # ── SCORE 7: Order Book (1 pt) ──
            s7, l7 = score_order_book(symbol, direction)

            # ── SCORE 8: News Sentiment (1 pt) ──
            s8, l8 = score_news(symbol, all_headlines)

            # ── TOTAL ──
            total_score = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8
            max_score   = 9

            print(f"  {symbol}: {direction.upper()} Score {total_score}/{max_score}")

            if total_score < MIN_SCORE:
                print(f"  SKIP {symbol}: Score too low ({total_score}/{max_score})")
                continue

            # ── SIGNAL CONFIRMED ──
            signal_type = "LONG" if direction == "bullish" else "SHORT"
            levels      = calculate_trade_levels(price, atr, direction)

            e = lambda s: "✅" if s >= 1 else "❌"
            e2 = lambda s: "✅" if s == 2 else "❌"

            message = (
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏆 HIGH QUALITY SIGNAL\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 {symbol}\n"
                f"📢 Signal: {signal_type}\n"
                f"🏦 Bitget Futures\n"
                f"⭐ Score: {total_score}/{max_score}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Analysis Breakdown\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{e2(s1)} {l1} (2pts)\n"
                f"{e(s2)} {l2}\n"
                f"{e(s3)} {l3}\n"
                f"{e(s4)} {l4}\n"
                f"{e(s5)} {l5}\n"
                f"{e(s6)} {l6}\n"
                f"{e(s7)} {l7}\n"
                f"{e(s8)} {l8}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Trade Execution\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 Entry: {levels['entry']}\n"
                f"🛑 Stop Loss: {levels['stop_loss']}\n"
                f"🎯 Take Profit: {levels['take_profit']}\n"
                f"⚖ Risk Reward: 1:{levels['rr']}\n\n"
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
