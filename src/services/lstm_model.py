"""
lstm_model.py — PyTorch LSTM Temporal Signal Model (Phase 2 / Task 4)

Replaces the stateless point-in-time XGBoost model with a continuous sequence
model that consumes a sliding window of 60 periods.

Input features per timestep (8 total):
  0  log_return         — log(close_t / close_{t-1})
  1  volume_norm        — volume / rolling_mean_volume (60-period)
  2  obi                — order book imbalance (bid_vol - ask_vol) / total_vol
  3  atr_norm           — ATR / close (relative volatility)
  4  rsi_norm           — (RSI - 50) / 50  (centred, range ≈ [-1, 1])
  5  ema_spread         — (ema_fast - ema_slow) / close
  6  macd_norm          — MACD histogram / ATR
  7  price_z            — (close - rolling_mean) / rolling_std

Output:
  scalar in (-1, +1) via tanh — positive = BUY edge, negative = SELL edge.
  |output| > EDGE_THRESHOLD → signal is actionable.

Architecture:
  LSTM(input=8, hidden=64, layers=2, dropout=0.2) → Linear(64, 1) → tanh

Training:
  Supervised on labelled sequences (label = sign of forward_pnl, weighted by |pnl|).
  Online fine-tuning: call model.update(window, label) after each trade close.

Integration with existing pipeline:
  1. Call LSTMSignalModel.predict(window) from signal_generator.on_price or RDE.
  2. The returned edge score is fused with the existing EV score:
       fused_ev = 0.7 * rde_ev + 0.3 * lstm_edge
  3. Full replacement of XGBoost is a future step — this module is an additive layer.

State persistence:
  Weights saved to WEIGHTS_PATH (local file) on every SAVE_EVERY updates.
  Hydrated from file on boot — no cold-start weight loss across restarts.

Requires: torch (pip install torch --index-url https://download.pytorch.org/whl/cpu)
Gracefully disabled when torch is unavailable — returns 0.0 (neutral) on predict().
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SEQ_LEN:         int   = 60       # sliding window length (periods)
INPUT_SIZE:      int   = 8        # features per timestep
HIDDEN_SIZE:     int   = 64
NUM_LAYERS:      int   = 2
DROPOUT:         float = 0.2
LR:              float = 1e-3
EDGE_THRESHOLD:  float = 0.15     # |output| must exceed this to be actionable
SAVE_EVERY:      int   = 20       # save weights every N online updates
WEIGHTS_PATH:    str   = os.getenv(
    "LSTM_WEIGHTS_PATH",
    os.path.join(os.path.dirname(__file__), "../../data/lstm_weights.pt"),
)

# ── Model definition ──────────────────────────────────────────────────────────

try:
    import torch
    import torch.nn as nn

    class _LSTMNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=INPUT_SIZE,
                hidden_size=HIDDEN_SIZE,
                num_layers=NUM_LAYERS,
                batch_first=True,
                dropout=DROPOUT if NUM_LAYERS > 1 else 0.0,
            )
            self.head = nn.Linear(HIDDEN_SIZE, 1)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # x: (batch, seq_len, input_size)
            out, _ = self.lstm(x)
            last    = out[:, -1, :]          # (batch, hidden)
            return torch.tanh(self.head(last))  # (batch, 1)

    _TORCH_AVAILABLE = True

except ImportError:
    _TORCH_AVAILABLE = False
    log.info("lstm_model: torch not available — LSTM inference disabled (returns 0.0)")


# ── Public API ────────────────────────────────────────────────────────────────

class LSTMSignalModel:
    """
    Stateful wrapper around _LSTMNet with online fine-tuning and weight persistence.

    Usage
    ─────
    model = LSTMSignalModel()          # loads weights from disk if available
    edge  = model.predict(window_60)   # window_60: np.ndarray shape (60, 8)
    model.update(window_60, label)     # label: +1 (win) or -1 (loss)
    """

    def __init__(self) -> None:
        self._net:       Optional[object] = None
        self._optimizer: Optional[object] = None
        self._updates:   int = 0
        self._enabled:   bool = _TORCH_AVAILABLE
        if self._enabled:
            self._build()
            self._load_weights()

    def _build(self) -> None:
        import torch.optim as optim
        self._net = _LSTMNet()
        self._net.eval()  # type: ignore[union-attr]
        self._optimizer = optim.Adam(self._net.parameters(), lr=LR)  # type: ignore[union-attr]

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, window: np.ndarray) -> float:
        """
        Return edge score in (-1, +1).
        Returns 0.0 when torch unavailable or window shape is wrong.

        Parameters
        ----------
        window : np.ndarray, shape (SEQ_LEN, INPUT_SIZE)
            Normalised feature matrix — caller is responsible for normalization.
        """
        if not self._enabled or self._net is None:
            return 0.0
        if window.shape != (SEQ_LEN, INPUT_SIZE):
            log.debug("lstm predict: bad shape %s, expected (%d,%d)",
                      window.shape, SEQ_LEN, INPUT_SIZE)
            return 0.0
        try:
            import torch
            self._net.eval()  # type: ignore[union-attr]
            with torch.no_grad():
                x = torch.tensor(window, dtype=torch.float32).unsqueeze(0)
                score = self._net(x).item()  # type: ignore[union-attr]
            return float(score)
        except Exception as exc:
            log.debug("lstm predict error: %s", exc)
            return 0.0

    def is_actionable(self, window: np.ndarray) -> tuple[bool, float]:
        """
        Returns (actionable, edge_score).
        actionable = True when |edge_score| > EDGE_THRESHOLD.
        """
        score = self.predict(window)
        return abs(score) > EDGE_THRESHOLD, score

    # ── Online fine-tuning ────────────────────────────────────────────────────

    def update(self, window: np.ndarray, label: float) -> None:
        """
        One-step gradient update on (window, label) pair.

        Parameters
        ----------
        window : np.ndarray, shape (SEQ_LEN, INPUT_SIZE)
        label  : +1.0 (win) or -1.0 (loss); can be weighted by |pnl|
        """
        if not self._enabled or self._net is None or self._optimizer is None:
            return
        if window.shape != (SEQ_LEN, INPUT_SIZE):
            return
        try:
            import torch
            import torch.nn.functional as F

            self._net.train()  # type: ignore[union-attr]
            x = torch.tensor(window, dtype=torch.float32).unsqueeze(0)
            y = torch.tensor([[float(label)]], dtype=torch.float32)

            self._optimizer.zero_grad()
            pred = self._net(x)  # type: ignore[union-attr]
            loss = F.mse_loss(pred, y)
            loss.backward()
            # Gradient clipping — prevents exploding gradients on noisy finance data
            torch.nn.utils.clip_grad_norm_(self._net.parameters(), max_norm=1.0)  # type: ignore[union-attr]
            self._optimizer.step()
            self._net.eval()  # type: ignore[union-attr]

            self._updates += 1
            if self._updates % SAVE_EVERY == 0:
                self._save_weights()
        except Exception as exc:
            log.debug("lstm update error: %s", exc)

    # ── Weight persistence ────────────────────────────────────────────────────

    def _save_weights(self) -> None:
        if not self._enabled or self._net is None:
            return
        try:
            import torch
            os.makedirs(os.path.dirname(os.path.abspath(WEIGHTS_PATH)), exist_ok=True)
            torch.save(self._net.state_dict(), WEIGHTS_PATH)  # type: ignore[union-attr]
            log.debug("lstm weights saved → %s (update #%d)", WEIGHTS_PATH, self._updates)
        except Exception as exc:
            log.debug("lstm save_weights error: %s", exc)

    def _load_weights(self) -> None:
        if not self._enabled or self._net is None:
            return
        if not os.path.exists(WEIGHTS_PATH):
            log.info("lstm_model: no saved weights at %s — starting fresh", WEIGHTS_PATH)
            return
        try:
            import torch
            state = torch.load(WEIGHTS_PATH, map_location="cpu", weights_only=True)
            self._net.load_state_dict(state)  # type: ignore[union-attr]
            self._net.eval()  # type: ignore[union-attr]
            log.info("lstm_model: weights loaded from %s", WEIGHTS_PATH)
        except Exception as exc:
            log.warning("lstm_model: could not load weights (%s) — starting fresh", exc)


# ── Feature window builder ────────────────────────────────────────────────────

def build_window(
    closes:   list[float],
    volumes:  list[float],
    bids_vol: list[float],
    asks_vol: list[float],
    atrs:     list[float],
    rsis:     list[float],
    ema_fast: list[float],
    ema_slow: list[float],
    macds:    list[float],
) -> Optional[np.ndarray]:
    """
    Build a (SEQ_LEN, INPUT_SIZE) feature matrix from raw price/indicator series.
    All input lists must have length ≥ SEQ_LEN + 1 (one extra for log-return diff).
    Returns None if insufficient data.

    Normalization is applied inline:
      log_return: raw (already scale-invariant)
      volume_norm: v / mean(v_window)  (relative, not absolute)
      obi: (bid - ask) / (bid + ask + ε)
      atr_norm: atr / close
      rsi_norm: (rsi - 50) / 50
      ema_spread: (fast - slow) / close
      macd_norm: macd / (atr + ε)
      price_z: (close - mean) / (std + ε)
    """
    n = SEQ_LEN + 1
    if any(len(s) < n for s in [closes, volumes, bids_vol, asks_vol,
                                 atrs, rsis, ema_fast, ema_slow, macds]):
        return None

    c   = np.array(closes[-n:],   dtype=np.float64)
    vol = np.array(volumes[-n:],  dtype=np.float64)
    bv  = np.array(bids_vol[-n:], dtype=np.float64)
    av  = np.array(asks_vol[-n:], dtype=np.float64)
    atr = np.array(atrs[-n:],     dtype=np.float64)
    rsi = np.array(rsis[-n:],     dtype=np.float64)
    ef  = np.array(ema_fast[-n:], dtype=np.float64)
    es  = np.array(ema_slow[-n:], dtype=np.float64)
    mcd = np.array(macds[-n:],    dtype=np.float64)

    # Slice to SEQ_LEN (drop the leading "extra" needed for diff)
    lr        = np.log(c[1:] / (c[:-1] + 1e-12))          # (SEQ_LEN,)
    c_w       = c[1:]
    vol_w     = vol[1:]
    bv_w      = bv[1:]
    av_w      = av[1:]
    atr_w     = atr[1:]
    rsi_w     = rsi[1:]
    ef_w      = ef[1:]
    es_w      = es[1:]
    mcd_w     = mcd[1:]

    vol_mean  = vol_w.mean() or 1.0
    c_mean    = c_w.mean()
    c_std     = c_w.std() or 1.0

    f0 = lr
    f1 = vol_w / vol_mean
    f2 = (bv_w - av_w) / (bv_w + av_w + 1e-9)
    f3 = atr_w / (c_w + 1e-9)
    f4 = (rsi_w - 50.0) / 50.0
    f5 = (ef_w - es_w) / (c_w + 1e-9)
    f6 = mcd_w / (atr_w + 1e-9)
    f7 = (c_w - c_mean) / (c_std + 1e-9)

    window = np.stack([f0, f1, f2, f3, f4, f5, f6, f7], axis=1)  # (SEQ_LEN, 8)

    # Clip to ±5σ to prevent outlier spikes from dominating gradients
    window = np.clip(window, -5.0, 5.0)

    return window.astype(np.float32)


# ── Module-level singleton ────────────────────────────────────────────────────

model: LSTMSignalModel = LSTMSignalModel()
