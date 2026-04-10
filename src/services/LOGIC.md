# Mathematical & Trading Logic Deep-Dive

This document details the core mathematical models and trading logic implemented in the HF-Quant 5.0 system.

## 1. Expected Value (EV) Strategy
The system is an **EV-Only Engine**. It does not trade based on simple "buy" signals; instead, it evaluates the mathematical expectancy of every setup.

### A. The EV Formula
The system uses the standard expectancy formula:
$$EV = (win\_prob \times RR) - (1 - win\_prob)$$
- **RR (Risk:Reward)**: Typically fixed at **1.25** in the decision engine (`TP=1.0 * ATR / SL=0.8 * ATR`).
- **win_prob**: The calibrated win probability (see below).

### B. EV Normalization (Tanh)
In `learning_monitor.py`, EV is bounded using a tanh-Sharpe ratio to prevent outliers (caused by near-zero standard deviation) from poisoning the global metrics:
$$true\_ev = \tanh\left(\frac{mean(PnL)}{max(std(PnL), 0.002)}\right)$$
- This ensures $true\_ev \in (-1, +1)$.

---

## 2. Bayesian Online Calibration
A raw "Confidence Score" from an ML model is often biased. The **Calibrator** in `realtime_decision_engine.py` maps these raw scores to empirical win rates.

- **Process**: 
  1. Internal buckets group signals by confidence (0.1 bins: 0.5, 0.6, 0.7...).
  2. For each bucket, it tracks `[wins, total]`.
  3. **Confidence-to-Reality Warp**: If a model predicts 80% confidence but the bucket's empirical WR is 45%, the `win_prob` used for the EV calculation becomes 45%.
- **Minimum Sample Size**: Requires ≥30 trades per bucket before the calibration is considered "Live". Until then, it defaults to a conservative 0.5 prior.

---

## 3. Portfolio Variance & Risk
Unlike simple fixed-percentage sizing, the **Risk Engine** uses a variance-budgeting model that is correlation-aware.

### A. Variance Calculation
Portfolio risk ($\sigma_p$) is calculated using the pairwise correlation heuristic:
$$\sigma_p = \sqrt{\sum r_i^2 + 2 \sum_{i<j} \rho_{ij} r_i r_j}$$
- $r_i$ = Individual position risk (Size × Stop-Loss %).
- $\rho_{ij}$ = Correlation coefficient.

### B. Correlation Heuristics ($\rho$)
To avoid heavy matrix math on every tick, the system uses "Regime-Direction" heuristics:
- **Same Direction + Same Regime**: $\rho = 0.70$ (Strong Concentration)
- **Same Direction + Diff Regime**: $\rho = 0.45$ (Moderate)
- **Opposite Direction**: $\rho = -0.20$ (Natural Hedge)

---

## 4. Signal Micro-Momentum (V6 L4)
To ensure the bot doesn't "catch a falling knife," it uses a micro-momentum check (`_price_history`) in the decision engine:
- It maintains the last 3 price ticks for each symbol.
- **Entry Guard**: A `BUY` signal is only executed if the current price is $\ge$ the average of the last 3 ticks (ensuring a flat or upward micro-drift at the moment of entry).

---

## 5. Order Book Imbalance (OBI)
Calculated in `market_stream.py` and used as a weight in the feature vector:
$$OBI = \frac{BidVolume - AskVolume}{BidVolume + AskVolume}$$
- **$OBI \in (-1, +1)$**: Positive values indicate heavy buying pressure at the top of the book.
