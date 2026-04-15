"""
Order Flow Imbalance (OFI) toxicity guard.

Tracks per-symbol price tick direction to detect one-sided order flow that
indicates a liquidation cascade or aggressive institutional flow against the
intended trade direction.

  OFI = (up_ticks − down_ticks) / total_ticks  ∈ [−1, +1]
  +1  = all ticks up   (strong buy pressure)
  −1  = all ticks down (strong sell pressure)

  Toxic entry: OFI strongly AGAINST intended direction.
    BUY  + OFI < −THRESHOLD → market being aggressively sold → skip
    SELL + OFI >  THRESHOLD → market being aggressively bought → skip

  Size dampener: when |OFI| is moderate (0.4–0.7), reduce position size
  instead of blocking entirely. Only hard-block at extreme levels.

Research basis:
  arXiv:2602.00776 — stable cross-asset OFI patterns on Binance Futures at
  1-second resolution; consistent predictive importance for OFI, spread, and
  adverse selection features across BTC/LTC/ETC/ENJ/ROSE.

Called from:
  learning_event.track_price()   → update_price()
  realtime_decision_engine.py    → is_toxic() / ofi_size_factor()
"""

from collections import deque

# Rolling tick window for OFI computation
_WINDOW          = 30     # last N price ticks (~30 seconds at 1s polling)
_BLOCK_THRESHOLD = 0.85   # V10.12d: raised 0.70→0.85 — only extreme OFI blocks (arXiv threshold)
_WARN_THRESHOLD  = 0.40   # |OFI| above this → size reduction

# Per-symbol rolling price history
_price_ticks: dict[str, deque] = {}   # sym → deque(maxlen=_WINDOW+1)


def update_price(sym: str, price: float) -> None:
    """
    Append latest price tick. Call from track_price() on every price update.
    O(1) amortized — deque auto-evicts oldest entry.
    """
    if sym not in _price_ticks:
        _price_ticks[sym] = deque(maxlen=_WINDOW + 1)
    _price_ticks[sym].append(float(price))


def ofi(sym: str) -> float:
    """
    Compute rolling OFI for symbol.
    Returns 0.0 when fewer than 5 ticks available (insufficient data).
    """
    hist = _price_ticks.get(sym, deque())
    prices = list(hist)
    if len(prices) < 5:
        return 0.0
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    up    = sum(1 for d in diffs if d > 0)
    down  = sum(1 for d in diffs if d < 0)
    total = up + down
    if total == 0:
        return 0.0
    return (up - down) / total


def is_toxic(sym: str, action: str) -> tuple[bool, str]:
    """
    Hard block: extreme OFI against intended direction.
    Returns (blocked: bool, reason: str).

    BUY  + OFI < −BLOCK_THRESHOLD → toxic sell flow → block
    SELL + OFI >  BLOCK_THRESHOLD → toxic buy  flow → block
    """
    flow = ofi(sym)
    if abs(flow) < _BLOCK_THRESHOLD:
        return False, ""
    if action == "BUY"  and flow < -_BLOCK_THRESHOLD:
        return True, f"OFI_TOXIC:flow={flow:+.2f} heavy sell pressure vs BUY"
    if action == "SELL" and flow >  _BLOCK_THRESHOLD:
        return True, f"OFI_TOXIC:flow={flow:+.2f} heavy buy pressure vs SELL"
    return False, ""


def ofi_size_factor(sym: str, action: str) -> float:
    """
    V10.12d: Graduated OFI size penalty (was: binary hard block).
    Only directional conflicts cause penalties.
    
    Returns multiplier ∈ [0.5, 1.0]:
      |OFI| < 0.40                → 1.0   (no penalty)
      0.40 ≤ |OFI| < 0.70         → 0.88  (slight)
      0.70 ≤ |OFI| < 0.85         → 0.78  (moderate)
      0.85 ≤ |OFI| (+ bad spread) → 0.50  (severe; hard block elsewhere)
    """
    flow = ofi(sym)
    against = (action == "BUY" and flow < 0) or (action == "SELL" and flow > 0)
    if not against:
        return 1.0
    
    magnitude = abs(flow)
    if magnitude >= _BLOCK_THRESHOLD:
        return 0.50   # extreme adverse OFI (hard block in is_toxic)
    elif magnitude >= 0.70:
        return 0.78   # strong adverse
    elif magnitude >= _WARN_THRESHOLD:
        return 0.88   # moderate adverse
    return 1.0


def ofi_snapshot() -> dict:
    """Diagnostic snapshot — call from monitoring or print_status()."""
    out = {}
    for sym, hist in _price_ticks.items():
        flow = ofi(sym)
        n    = len(hist)
        out[sym] = {"ofi": round(flow, 3), "ticks": n}
    return out
