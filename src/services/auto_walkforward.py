from src.services.firebase_client import load_history, load_auditor_state, save_auditor_state
import time
import numpy as _np

_LAST_RUN = 0

def calibrate_limits():
    """
    Auto-Walk-Forward Optimizace (AWO)
    Využívá historická data MAE (Maximum Adverse Excursion) pro dynamické posouvání Stop-Loss hranice.
    Každý trh se mění, místo tipování konstant (-0.40%) si algoritmus zpětně odsimuluje 
    přesnou historickou equity křivku a použije SL z nejziskovější nalezené varianty.
    """
    global _LAST_RUN
    # Spustit kalibraci pouze jednou za 12 hodin (nebo na tvrdý boot)
    if time.time() - _LAST_RUN < 43200:
        return
        
    trades = load_history(150)
    # Systém potřebuje plně zahřátá HF Quant data (alespoň 30 obchodů vybavených MAE senzory)
    valid_trades = [t for t in trades if "mae" in t and abs(float(t["mae"])) > 0.0]
    
    if len(valid_trades) < 30:
        return

    best_equity = -99999
    best_sl = 0.004
    
    # Testujeme SL od 0.15% do 0.80% (v krocích po 0.05%)
    sl_candidates = [x / 10000.0 for x in range(15, 85, 5)]
    
    for test_sl in sl_candidates:
        hypothetical_equity = 0.0
        
        for t in valid_trades:
            mae = float(t["mae"])
            actual_profit_pct = float(t.get("profit", 0.0)) / max(float(t.get("price", 1)), 1e-9)
            
            # Pokud MAE dosáhlo testovaného SL už předtím, než se obchod stihl zavřít v budoucnu
            # simulujeme dřívější ustřihnutí ztráty limitní páskou:
            if mae <= -test_sl:
                hypothetical_equity -= test_sl
            else:
                # Obchod přežil náš testovaný limit a zavřel se tam, kde doopravdy, bereme plný zisk
                hypothetical_equity += actual_profit_pct
                
        if hypothetical_equity > best_equity:
            best_equity = hypothetical_equity
            best_sl = test_sl

    print(f"🤖 AUTO-WALKFORWARD: Z předchozích MFE/MAE dat nalezen optimální SL limit: {best_sl*100:.2f}%")

    state = load_auditor_state()
    state["min_sl_pct"] = best_sl
    state["last_calibrated"] = time.time()
    save_auditor_state(state)

    _LAST_RUN = time.time()
    _CALIBRATED_SL = best_sl

    # Run Monte Carlo validation over same trade set (reuses already-loaded data)
    monte_carlo_validation(trades)

_CALIBRATED_SL = 0.004

def get_best_sl():
    global _CALIBRATED_SL, _LAST_RUN
    if time.time() - _LAST_RUN > 43200:
        calibrate_limits()
    return _CALIBRATED_SL


def monte_carlo_validation(trades: list, n_sim: int = 2000) -> dict:
    """
    Bootstrap Monte Carlo simulation over closed trades.

    Shuffles the profit series n_sim times to estimate the distribution of
    outcomes independent of trade ordering, producing robust tail-risk metrics
    that a single equity curve cannot reveal.

    Metrics returned
    ────────────────
    p5_equity      : 5th percentile final equity (worst-case scenario)
    p95_equity     : 95th percentile final equity (best-case scenario)
    p95_max_dd     : 95th percentile maximum drawdown across simulations
    prob_ruin      : fraction of paths ending below –20% cumulative loss
    median_equity  : median final equity across simulations
    n_trades       : number of trades used in simulation

    Requires ≥ 30 trades with a "profit" field.
    Returns {} if insufficient data.

    Research: Bootstrap resampling of trade returns (Davison & Hinkley 1997)
    removes autocorrelation bias from sequential backtests and gives
    distribution-free confidence intervals robust to non-normality.
    """
    valid = [t for t in trades if "profit" in t and "price" in t]
    if len(valid) < 30:
        return {}

    returns = _np.array([
        float(t["profit"]) / max(float(t.get("price", 1)), 1e-9)
        for t in valid
    ], dtype=float)

    n = len(returns)
    rng = _np.random.default_rng(seed=42)

    final_equities = _np.empty(n_sim)
    max_drawdowns  = _np.empty(n_sim)

    for i in range(n_sim):
        path   = rng.choice(returns, size=n, replace=True)
        equity = _np.cumsum(path)
        peak   = _np.maximum.accumulate(equity)
        dd     = (peak - equity)
        final_equities[i] = equity[-1]
        max_drawdowns[i]  = dd.max()

    RUIN_THRESHOLD = -0.20   # 20% cumulative loss = ruin

    result = {
        "p5_equity":    round(float(_np.percentile(final_equities,  5)), 6),
        "p95_equity":   round(float(_np.percentile(final_equities, 95)), 6),
        "median_equity":round(float(_np.median(final_equities)),         6),
        "p95_max_dd":   round(float(_np.percentile(max_drawdowns,   95)), 6),
        "prob_ruin":    round(float((final_equities < RUIN_THRESHOLD).mean()), 4),
        "n_trades":     n,
    }

    print(
        f"🎲 MONTE CARLO (n={n_sim}, trades={n}): "
        f"p5={result['p5_equity']:+.3%}  p95={result['p95_equity']:+.3%}  "
        f"p95_dd={result['p95_max_dd']:.3%}  ruin={result['prob_ruin']:.1%}"
    )

    # Persist into auditor state so auditor + advice use the latest values
    try:
        state = load_auditor_state()
        state["monte_carlo"] = result
        state["monte_carlo"]["updated_at"] = time.time()
        save_auditor_state(state)
    except Exception:
        pass

    return result

