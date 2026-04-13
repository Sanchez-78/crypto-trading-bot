from __future__ import annotations
import numpy as np


def depth_weighted_obi(
    bid_vols: list,
    ask_vols: list,
    n: int = 10,
    decay: float = 3.0,
) -> float:
    """Exponentially-decayed Order Book Imbalance.

    Sources: Cont, Kukanov & Stoikov (2014) R²≥50% 44/50 NYSE;
    arXiv:2507.22712 trade-events > LOB.
    """
    n = min(n, len(bid_vols), len(ask_vols))
    w = np.array([0.5 ** (i / decay) for i in range(n)])
    wb = np.sum(np.array(bid_vols[:n]) * w)
    wa = np.sum(np.array(ask_vols[:n]) * w)
    d = wb + wa
    return (wb - wa) / d if d > 0 else 0.0


def spoof_score(
    bid_vols: list,
    ask_vols: list,
    prev_snapshots: list,
    n: int = 10,
) -> float:
    """Multi-factor spoofing score [0, 1].

    Sources: Fabre & Challet (2025) 31% large orders spoof;
    Do & Putniņš (2023) AUC-ROC 0.97.
    """
    score = 0.0
    bv = np.array(bid_vols[:n], dtype=float)
    med = np.median(bv)
    score += 0.3 * (np.sum(bv > 3.0 * med) / n if med > 0 else 0)
    if n >= 5:
        near = np.mean(bv[:2])
        far = np.mean(bv[3:n])
        if near > 0 and far / near > 3.0:
            score += 0.3
    if len(prev_snapshots) >= 3:
        churn = sum(
            abs(bv[i] - np.array(prev)[i]) > 0.5 * max(float(bv[i]), float(np.array(prev)[i]), 1e-9)
            for prev in prev_snapshots[-5:]
            for i in range(3, min(n, len(prev)))
        )
        score += 0.4 * min(churn / max(5 * (n - 3), 1), 1.0)
    return min(score, 1.0)


def adjusted_obi(
    bid_vols: list,
    ask_vols: list,
    prev_snapshots: list,
) -> dict:
    """OBI adjusted for spoofing + quality classification.

    Quality tiers:
      HIGH   — |adj_obi| ≥ 0.24, spoof < 0.2  → full size 1.0
      MEDIUM — |adj_obi| ≥ 0.15, spoof < 0.5  → half size 0.5
      NEUTRAL— |adj_obi| < 0.10               → skip
      LOW    — else                             → skip
    """
    obi = depth_weighted_obi(bid_vols, ask_vols)
    sp = spoof_score(bid_vols, ask_vols, prev_snapshots)
    adj = obi * (1.0 - sp)
    if abs(adj) >= 0.24 and sp < 0.2:
        q, sz = "HIGH", 1.0
    elif abs(adj) >= 0.15 and sp < 0.5:
        q, sz = "MEDIUM", 0.5
    elif abs(adj) < 0.10:
        q, sz = "NEUTRAL", 0.0
    else:
        q, sz = "LOW", 0.0
    return {"obi": obi, "spoof": sp, "adj_obi": adj, "quality": q, "size": sz}
