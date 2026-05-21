import os
import json
import requests
import ccxt
import pandas as pd

from dotenv import load_dotenv
from datetime import datetime, timedelta

# =====================================
# LOAD ENV
# =====================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

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

MIN_RR = 2.0
SIGNAL_COOLDOWN_HOURS = 12
COOLDOWN_FILE = "last_signal_times.json"

# =====================================
# ALL COINS (Bitget Futures format)
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
# LOAD DATA
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
# INDICATORS (pure pandas)
# =====================================

def apply_indicators(df):

    # EMA
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # ATR
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=13, adjust=False).mean()

    # Volume
    df["vol_ma"]  = df["volume"].rolling(20).mean()
    df["rel_vol"] = df["volume"] / df["vol_ma"]

    return df

# =====================================
# 1H TREND CHECK
# =====================================

def check_1h_trend(symbol):
    df = load_ohlcv(symbol, "1h", limit=60)
    df = apply_indicators(df)

    ema20 = df["ema_20"].iloc[-1]
    ema50 = df["ema_50"].iloc[-1]
    price = df["close"].iloc[-1]

    if ema20 > ema50 and price > ema20:
        return "bullish"

    if ema20 < ema50 and price < ema20:
        return "bearish"

    return None

# =====================================
# 15M ENTRY CHECK
# =====================================

def check_15m_entry(symbol, direction):
    df = load_ohlcv(symbol, "15m", limit=60)
    df = apply_indicators(df)

    ema20    = df["ema_20"].iloc[-1]
    ema50    = df["ema_50"].iloc[-1]
    rsi      = df["rsi"].iloc[-1]
    macd     = df["macd"].iloc[-1]
    macd_sig = df["macd_signal"].iloc[-1]
    rel_vol  = df["rel_vol"].iloc[-1]
    price    = df["close"].iloc[-1]
    atr      = df["atr"].iloc[-1]

    details = {
        "price":   round(price, 4),
        "rsi":     round(rsi, 2),
        "macd":    round(macd, 6),
        "rel_vol": round(rel_vol, 2),
        "atr":     round(atr, 6),
    }

    if direction == "bullish":
        ema_ok  = ema20 > ema50
        rsi_ok  = 45 <= rsi <= 70
        macd_ok = macd > macd_sig
        vol_ok  = rel_vol >= 0.8

    else:
        ema_ok  = ema20 < ema50
        rsi_ok  = 30 <= rsi <= 55
        macd_ok = macd < macd_sig
        vol_ok  = rel_vol >= 0.8

    details["checks"] = {
        "ema_aligned": ema_ok,
        "rsi_ok":      rsi_ok,
        "macd_ok":     macd_ok,
        "volume_ok":   vol_ok,
    }

    valid = ema_ok and rsi_ok and macd_ok and vol_ok

    return valid, details

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

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

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

    for symbol in ALL_SYMBOLS:

        try:

            # Check cooldown
            if is_on_cooldown(symbol, signal_times, now):
                last = signal_times[symbol]
                remaining = last + timedelta(hours=SIGNAL_COOLDOWN_HOURS) - now
                hrs  = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                print(f"  COOLDOWN {symbol}: {hrs}h {mins}m left")
                continue

            # Step 1: 1H Trend
            trend_1h = check_1h_trend(symbol)

            if trend_1h is None:
                print(f"  SKIP {symbol}: 1H trend unclear")
                continue

            print(f"  {symbol}: 1H = {trend_1h.upper()} → checking 15M...")

            # Step 2: 15M Entry
            valid, details = check_15m_entry(symbol, trend_1h)

            if not valid:
                checks = details["checks"]
                failed = [k for k, v in checks.items() if not v]
                print(f"  SKIP {symbol}: 15M failed → {failed}")
                continue

            # All checks passed
            signal_type = "LONG" if trend_1h == "bullish" else "SHORT"

            levels = calculate_trade_levels(
                details["price"],
                details["atr"],
                trend_1h
            )

            checks = details["checks"]

            message = (
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏆 HIGH QUALITY SIGNAL\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 Symbol: {symbol}\n"
                f"📢 Signal: {signal_type}\n"
                f"🏦 Exchange: Bitget Futures\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 Multi-Timeframe Analysis\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"⏰ 1H Trend: {trend_1h.upper()} ✅\n"
                f"📈 15M EMA Aligned: {'✅' if checks['ema_aligned'] else '❌'}\n"
                f"💨 RSI: {details['rsi']} {'✅' if checks['rsi_ok'] else '❌'}\n"
                f"⚡ MACD: {'✅' if checks['macd_ok'] else '❌'}\n"
                f"📦 Volume: {details['rel_vol']}x {'✅' if checks['volume_ok'] else '❌'}\n\n"
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

            print(f"  ✅ SIGNAL: {symbol} → {signal_type}")
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
