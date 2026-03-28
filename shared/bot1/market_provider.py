import sys, os
sys.path.append(os.getcwd())

from src.services.binance_client   import fetch_candles
from src.services.feature_extractor import extract_multi_tf_features


class MarketProvider:
    """
    Live market data provider — replaces the random stub.

    Fetches OHLCV candles from Binance for three timeframes (15m / 1h / 4h)
    and computes multi-timeframe alpha features via feature_extractor.
    Returns the same dict shape the ML model and risk engine expect.
    Returns None if Binance is unreachable or returns too few candles.
    """

    def get_features(self, symbol: str = "BTCUSDT") -> dict | None:
        candles_m15 = fetch_candles(symbol, "15m")
        candles_h1  = fetch_candles(symbol, "1h")
        candles_h4  = fetch_candles(symbol, "4h")

        if not candles_m15 or not candles_h1 or not candles_h4:
            print(f"⚠️  MarketProvider: no candles for {symbol}")
            return None

        features = extract_multi_tf_features(candles_m15, candles_h1, candles_h4)
        if not features:
            print(f"⚠️  MarketProvider: feature extraction failed for {symbol}")
            return None

        features["symbol"] = symbol
        return features
