BASE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]


def get_active_symbols(top_n=0) -> list[str]:
    """Returns the fixed symbol set: BTC, ETH, ADA, BNB, DOT, SOL, XRP.

    Dynamic altcoin discovery removed — concentrates learning data on a fixed
    set of liquid, high-volume pairs instead of spreading trades across many
    symbol×regime combinations where most never converge.
    """
    return list(BASE_SYMBOLS)


if __name__ == "__main__":
    print(get_active_symbols())
