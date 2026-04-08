BASE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]


def get_active_symbols(top_n=0) -> list[str]:
    """Returns the fixed symbol set: BTC, ETH, ADA only.

    Dynamic altcoin discovery removed — concentrates learning data on three
    liquid, high-volume pairs instead of spreading 246 trades across 20+
    symbol×regime combinations where most never converge.
    """
    return list(BASE_SYMBOLS)


if __name__ == "__main__":
    print(get_active_symbols())
