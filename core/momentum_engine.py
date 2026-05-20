def analyze_momentum(df):

    roc = df["roc"].iloc[-1]

    rsi = df["rsi"].iloc[-1]

    strong = abs(roc) > 2

    return {
        "roc": round(roc, 2),
        "rsi": round(rsi, 2),
        "strong": strong
    }
