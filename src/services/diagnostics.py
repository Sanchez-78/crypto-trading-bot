"""
Failure mode detection + execution-aware backtest.

Failure modes detected:
  OVERFIT        — recent WR drops >15pp vs historical for a (sym,reg) pair
  REGIME_SHIFT   — vol or trend change >1% over last 30 bars
  EXEC_DECAY     — recent slip mean >1.5× historical mean
  ALLOC_BIAS     — one position holds >40% of total deployed capital
  DRAWDOWN       — peak drawdown >15% in last 20 equity samples

BacktestEngine:
  Uses real execution.py functions (slippage, ev_adjust, final_size, cost_guard).
  Slippage applied as fractional fill: fill_price = price * (1 + slip_frac).
  OB built via OrderBook.from_price — consistent with live path.
"""

import numpy as np

from src.services.execution import (
    trade_log, slippage_hist, returns_hist, closed_trades,
    slippage, ev_adjust, final_size, entry_filter, cost_guard,
    bayes_update, bandit_update, detect_regime, update_returns,
    OrderBook,
)

# ── Diagnostic state ───────────────────────────────────────────────────────────

equity_curve: list = []
drawdowns:    list = []
_d_equity:    list = [1.0]
_d_peak:      list = [1.0]


def update_equity_curve(pnl):
    """Update diagnostic equity curve and drawdown series."""
    _d_equity[0] += float(pnl)
    _d_peak[0]    = max(_d_peak[0], _d_equity[0])
    dd = (_d_peak[0] - _d_equity[0]) / max(_d_peak[0], 1e-9)
    equity_curve.append(_d_equity[0])
    drawdowns.append(dd)


# ── Failure mode detectors ────────────────────────────────────────────────────

def detect_overfit(sym, reg):
    """
    Recent WR < historical WR − 15pp → overfitting signal.
    Requires ≥30 closed trades for (sym, reg); split 20 recent vs remainder.
    """
    trades = [t for t in closed_trades
              if t["sym"] == sym and t["reg"] == reg]
    if len(trades) < 30:
        return False
    recent = trades[-20:]
    old    = trades[:-20]
    if len(old) < 10:
        return False
    wr_recent = sum(1 for t in recent if t["pnl"] > 0) / len(recent)
    wr_old    = sum(1 for t in old    if t["pnl"] > 0) / len(old)
    return wr_recent < wr_old - 0.15


def detect_regime_shift(sym):
    """
    Vol or trend delta >1% between last 20 bars and prior 30 bars.
    Signals that the market structure has changed beneath the strategy.
    """
    r = returns_hist.get(sym, [])
    if len(r) < 50:
        return False
    vol_now   = float(np.std(r[-20:]))
    vol_prev  = float(np.std(r[-50:-20]))
    trend_now  = float(np.mean(r[-20:]))
    trend_prev = float(np.mean(r[-50:-20]))
    return abs(vol_now - vol_prev) > 0.01 or abs(trend_now - trend_prev) > 0.01


def detect_execution_decay(sym):
    """
    Recent slip mean (last 10) > 1.5× lifetime mean → execution quality degrading.
    Possible cause: liquidity conditions changed or fill rate dropped.
    """
    slips = slippage_hist.get(sym, [])
    if len(slips) < 30:
        return False
    return float(np.mean(slips[-10:])) > float(np.mean(slips[:-10])) * 1.5


def detect_allocation_bias(positions):
    """
    One position holds >40% of total deployed capital → concentration risk.
    """
    sizes = [p["size"] for p in positions.values()]
    if len(sizes) < 2:
        return False
    return max(sizes) > 0.4 * sum(sizes)


def detect_drawdown_risk():
    """Max drawdown in last 20 equity samples exceeds 15%."""
    if len(drawdowns) < 20:
        return False
    return max(drawdowns[-20:]) > 0.15


def failure_scan(positions=None):
    """
    Run all failure detectors. Returns list of active risk flags.
    Call periodically (e.g. every N ticks) to catch degradation early.
    """
    if positions is None:
        positions = {}
    flags = []
    for sym in list(returns_hist):
        reg = detect_regime(sym)
        if detect_overfit(sym, reg):
            flags.append(f"OVERFIT_{sym}")
        if detect_regime_shift(sym):
            flags.append(f"REGIME_SHIFT_{sym}")
        if detect_execution_decay(sym):
            flags.append(f"EXEC_DECAY_{sym}")
    if detect_allocation_bias(positions):
        flags.append("ALLOC_BIAS")
    if detect_drawdown_risk():
        flags.append("DRAWDOWN")
    return flags


# ── Backtest engine ───────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Execution-aware backtest using live execution.py functions.

    Tick format:
      {"sym": str, "price": float,
       "ret": float (optional — for returns_hist),
       "ws": float  (optional — raw weighted score),
       "next_price": float (optional — exit price; defaults to entry)}

    Slippage is fractional: fill_price = price * (1 + slip_frac).
    OB is built via OrderBook.from_price (consistent with live path).
    """

    def __init__(self, data):
        self.data    = data
        self.results = []
        self._equity = 1.0

    def _simulate_ob(self, price):
        return OrderBook.from_price(price, spread_pct=0.0005)

    def run(self):
        for tick in self.data:
            sym   = tick["sym"]
            price = float(tick["price"])

            # Feed returns history (required by detect_regime, vol, etc.)
            ret = tick.get("ret", 0.0)
            returns_hist.setdefault(sym, []).append(float(ret))
            if len(returns_hist[sym]) > 200:
                returns_hist[sym].pop(0)

            ob  = self._simulate_ob(price)
            reg = detect_regime(sym)

            if not entry_filter(sym, reg):
                continue

            ws   = float(tick.get("ws", 0.5))
            ws   = ev_adjust(ws, sym, reg)
            size = final_size(sym, reg, 0.02, {}, ob)

            if size <= 0:
                continue
            if not cost_guard(ws, size, ob, 0.0006, sym):
                continue

            # Fractional slippage → realistic fill price
            slip_frac  = slippage(size, ob)
            fill_price = price * (1.0 + slip_frac)

            next_price = float(tick.get("next_price", price))
            pnl        = (next_price - fill_price) * size

            trade_log.append({
                "sym":  sym,
                "reg":  reg,
                "ws":   ws,
                "slip": slip_frac,
            })
            if len(trade_log) > 500:
                trade_log.pop(0)

            slippage_hist.setdefault(sym, []).append(slip_frac)
            if len(slippage_hist[sym]) > 100:
                slippage_hist[sym].pop(0)

            closed_trades.append({"sym": sym, "reg": reg, "pnl": pnl})
            if len(closed_trades) > 500:
                closed_trades.pop(0)

            update_equity_curve(pnl)
            bayes_update(sym, reg, pnl)
            bandit_update(sym, reg, 1 if pnl > 0 else 0)

            self._equity  += pnl
            self.results.append(self._equity)

        return self.results


# ── Backtest metrics ──────────────────────────────────────────────────────────

def sharpe():
    """Annualised-style Sharpe of equity_curve increments."""
    if len(equity_curve) < 2:
        return 0.0
    r = np.diff(equity_curve)
    return float(np.mean(r)) / (float(np.std(r)) + 1e-6)


def max_drawdown():
    """Peak drawdown from equity_curve history."""
    return float(max(drawdowns)) if drawdowns else 0.0


def winrate():
    """Win rate of closed_trades populated during backtest."""
    if not closed_trades:
        return 0.0
    return sum(1 for t in closed_trades if t["pnl"] > 0) / len(closed_trades)


def avg_edge():
    """Mean net edge (ws − slip) across trade_log entries."""
    if not trade_log:
        return 0.0
    return float(np.mean([t["ws"] - t["slip"] for t in trade_log]))
