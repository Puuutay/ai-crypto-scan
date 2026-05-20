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
