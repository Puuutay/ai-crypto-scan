from config.settings import MIN_RR


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
