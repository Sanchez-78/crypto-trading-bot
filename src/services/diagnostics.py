"""
Failure mode scoring + execution-aware backtest (no lookahead bias).

Failure detectors return continuous severity scores (0 = healthy):
  detect_overfit        — WR degradation magnitude (max 1.0)
  detect_regime_shift   — vol + trend delta (unbounded, ~0 healthy)
  detect_execution_decay — slip creep above baseline (unbounded)
  detect_allocation_bias — largest position fraction (0–1)
  detect_drawdown_risk  — peak drawdown in last 20 samples (0–1)

failure_score(positions) — weighted sum; threshold ~1.5 warrants action.

BacktestEngine:
  simulate_orderbook: stochastic spread ∈ [0.03%, 0.10%] + depth ∈ [0.5×, 2×].
  Exit price: data[i+delay] where delay ∈ {1,2,3} — no lookahead.
  Iterates data[:-5] so all delay offsets are safe.
  Uses real execution.py functions throughout.
"""

import numpy as np

from src.services.execution import (
    trade_log, slippage_hist, returns_hist, closed_trades,
    slippage, ev_adjust, final_size, entry_filter, cost_guard,
    bayes_update, bandit_update, detect_regime, update_returns,
    OrderBook,
)

# ── Diagnostic state ───────────────────────────────────────────────────────────

_d_equity: list = []
_d_peak:   list = [1.0]   # mutable scalar — avoids global keyword
drawdowns: list = []


def update_equity_curve(pnl):
    eq = (_d_equity[-1] if _d_equity else 1.0) + float(pnl)
    _d_peak[0] = max(_d_peak[0], eq)
    dd = (_d_peak[0] - eq) / max(_d_peak[0], 1e-9)
    _d_equity.append(eq)
    drawdowns.append(dd)


# ── Failure mode detectors (continuous severity scores) ───────────────────────

def detect_overfit(sym, reg):
    """
    WR degradation: max(0, wr_old − wr_recent).
    Returns 0 when insufficient data or no degradation.
    Requires ≥40 closed trades — splits into 20 recent vs ≥20 historical.
    """
    trades = [t for t in closed_trades
              if t["sym"] == sym and t["reg"] == reg]
    if len(trades) < 40:
        return 0.0
    recent = trades[-20:]
    old    = trades[:-20]
    if len(old) < 20:
        return 0.0
    wr_recent = sum(1 for t in recent if t["pnl"] > 0) / len(recent)
    wr_old    = sum(1 for t in old    if t["pnl"] > 0) / len(old)
    return float(max(0.0, wr_old - wr_recent))


def detect_regime_shift(sym):
    """
    |Δvol| + |Δtrend| between last 20 bars and prior 30 bars.
    ~0 = stable; >0.02 typically warrants attention.
    """
    r = returns_hist.get(sym, [])
    if len(r) < 50:
        return 0.0
    v1 = float(np.std(r[-20:]))
    v2 = float(np.std(r[-50:-20]))
    t1 = float(np.mean(r[-20:]))
    t2 = float(np.mean(r[-50:-20]))
    return abs(v1 - v2) + abs(t1 - t2)


def detect_execution_decay(sym):
    """
    Recent slip mean − lifetime mean (zero-floored).
    >0 means fills are getting worse; threshold ~0.001 is meaningful.
    """
    slips = slippage_hist.get(sym, [])
    if len(slips) < 30:
        return 0.0
    return float(max(0.0, np.mean(slips[-10:]) - np.mean(slips[:-10])))


def detect_allocation_bias(positions):
    """
    Largest position as fraction of total deployed capital (0–1).
    >0.4 is concentrated; returns 0 if <3 positions.
    """
    sizes = [p["size"] for p in positions.values()]
    if len(sizes) < 3:
        return 0.0
    return float(max(sizes) / (sum(sizes) + 1e-6))


def detect_drawdown_risk():
    """Peak drawdown in last 20 equity samples (0–1). 0 if insufficient data."""
    if len(drawdowns) < 20:
        return 0.0
    return float(max(drawdowns[-20:]))


def failure_score(positions=None):
    """
    Weighted severity score across all failure modes.
    Weights: overfit×2, regime_shift×1, exec_decay×2, alloc_bias×1, drawdown×3.
    ~0.0 = healthy  |  >1.5 = investigate  |  >3.0 = consider halting.
    """
    if positions is None:
        positions = {}
    score = 0.0
    for sym in list(returns_hist):
        reg    = detect_regime(sym)
        score += 2.0 * detect_overfit(sym, reg)
        score += 1.0 * detect_regime_shift(sym)
        score += 2.0 * detect_execution_decay(sym)
    score += 1.0 * detect_allocation_bias(positions)
    score += 3.0 * detect_drawdown_risk()
    return score


# ── Backtest engine ───────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Execution-aware backtest with stochastic OB and execution delay.

    Tick format:
      {"sym": str, "price": float,
       "ret": float  (optional),
       "ws":  float  (optional, default 0.5),
       "next_price": float  (ignored — exit is data[i+delay])}

    No lookahead: exit price = data[i + delay] where delay ~ Uniform(1,3).
    Stochastic OB: spread ∈ [0.03%, 0.10%], depth ∈ [0.5×, 2.0×] per tick.
    Iterates data[:-5] so all delay offsets are safe.
    """

    def __init__(self, data):
        self.data    = data
        self.results = []
        self.equity  = 1.0

    def _simulate_ob(self, price):
        spread_pct = np.random.uniform(0.0003, 0.001)
        depth      = np.random.uniform(0.5, 2.0)
        return OrderBook.from_price(price, spread_pct, depth)

    def run(self):
        for i, tick in enumerate(self.data[:-5]):
            sym   = tick["sym"]
            price = float(tick["price"])

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

            slip_frac  = slippage(size, ob)
            fill_price = price * (1.0 + slip_frac)

            delay       = np.random.randint(1, 4)
            future_price = float(self.data[i + delay]["price"])
            pnl          = (future_price - fill_price) * size

            trade_log.append({"sym": sym, "reg": reg, "ws": ws, "slip": slip_frac})
            if len(trade_log) > 500:
                trade_log.pop(0)

            closed_trades.append({"sym": sym, "reg": reg, "pnl": pnl,
                                   "ws": ws, "slip": slip_frac})
            if len(closed_trades) > 500:
                closed_trades.pop(0)

            slippage_hist.setdefault(sym, []).append(slip_frac)
            if len(slippage_hist[sym]) > 100:
                slippage_hist[sym].pop(0)

            update_equity_curve(pnl)
            bayes_update(sym, reg, pnl)
            bandit_update(sym, reg, 1 if pnl > 0 else 0)

            self.equity  += pnl
            self.results.append(self.equity)

        return self.results


# ── Backtest metrics ──────────────────────────────────────────────────────────

def sharpe():
    """Mean/std of equity increments. 0 if fewer than 2 data points."""
    if len(_d_equity) < 2:
        return 0.0
    r = np.diff(_d_equity)
    return float(np.mean(r)) / (float(np.std(r)) + 1e-6)


def max_drawdown():
    """Peak drawdown across full equity_curve history."""
    return float(max(drawdowns)) if drawdowns else 0.0


def winrate():
    """Win rate of closed_trades (backtest or production)."""
    if not closed_trades:
        return 0.0
    return sum(1 for t in closed_trades if t["pnl"] > 0) / len(closed_trades)


def avg_edge():
    """Mean net edge (ws − slip) across closed_trades."""
    if not closed_trades:
        return 0.0
    return float(np.mean([t["ws"] - t["slip"] for t in closed_trades]))
