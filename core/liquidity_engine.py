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
