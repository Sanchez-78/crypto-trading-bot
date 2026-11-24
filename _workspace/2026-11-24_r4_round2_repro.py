"""Read-only reproduction: a legitimate dynamic trailing stop can cross TP."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy" / "research_eval"))

import deploy_env_check as dec
from src.services.dynamic_trend_exit_v1 import ExitEvaluationInput, evaluate_exit

now = time.time()
base = {
    "trade_id": "review-long", "symbol": "BTCUSDT", "side": "BUY",
    "entry_price": 100.0, "tp": 100.35, "sl": 99.7,
    "entry_ts": now - 60, "size_usd": 7.5,
    "timeout_s": 1200.0, "max_hold_s": None,
    "paper_cost_contract_version": 1,
    "paper_fee_round_trip_fraction": 0.0008,
    "paper_slippage_round_trip_fraction": 0.0001,
    "strategy_id": "trend_cost_aware",
    "explore_bucket": "P0_8_PLUS_EVIDENCE_COLLECTION",
    "dynamic_exit_initial_stop": 99.7,
}

before = dec.open_positions_count(json.dumps({"review-long": base}), now=now)
decision = evaluate_exit(ExitEvaluationInput(
    side="BUY", entry_price=100.0, current_price=100.5,
    initial_stop_price=99.7, current_stop_price=99.7,
    target_reference_price=100.35, entry_time_ms=int((now - 60) * 1000),
    now_ms=int(now * 1000), max_hold_seconds=1200,
    atr_bps=10.0, mfe_bps=50.0, regime="BULL_TREND",
))
print("before_accepted", before)
print("decision", decision.reason_code, "new_stop", decision.new_stop_price)
after = {**base, "sl": decision.new_stop_price}
try:
    dec.open_positions_count(json.dumps({"review-long": after}), now=now)
except dec.Refused as exc:
    print("after_refused", str(exc))
else:
    print("after_accepted")
