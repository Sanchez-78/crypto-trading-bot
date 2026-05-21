# Claude Code Prompt — CryptoMaster Android Metrics Catalog

## Goal

Create a complete, implementation-ready catalog of all meaningful CryptoMaster bot metrics for an Android app that monitors:

- current robot health/status,
- market/data-feed state,
- signal and decision pipeline,
- open positions and trade history,
- paper/live trading performance,
- LearningMonitor state and learning quality,
- paper-training diagnostics,
- risk, safety, and data-quality warnings,
- success rate, profitability, and attribution of failures.

The output must help an Android developer build a clear Czech-language dashboard for controlling the state of the bot, its learning, trades, and success.

---

## Context

Project root:

```text
C:\Projects\CryptoMaster_srv
```

Production server path may be:

```text
/opt/cryptomaster
```

The bot is an event-driven crypto trading system using:

```text
WebSocket/market stream → signal_generator → realtime_decision_engine/RDE → trade_executor/paper_trade_executor → learning_monitor → Firebase/Firestore + logs
```

Important concepts and logs that must be considered:

```text
PAPER_TRAIN_ENTRY
PAPER_TRAIN_QUALITY_ENTRY
PAPER_TRAIN_QUALITY_EXIT
PAPER_TRAIN_ECON_ATTRIB
PAPER_TRAIN_ECON_SUMMARY
PAPER_TRAIN_QUALITY_SUMMARY
PAPER_EXIT
LM_STATE_AFTER_UPDATE
LM_UPDATE_MISMATCH
PAPER_SCORE_MISSING_CONTEXT
PAPER_TRAIN_QUALITY_MISMATCH
PAPER_TRAIN_QUALITY_EXIT_MISSING
PAPER_TRAIN_ANOMALY
COST_EDGE_BYPASS
COST_EDGE_BYPASS_ACCEPTED
COST_EDGE_BYPASS_FLOW
PAPER_ENTRY_ATTEMPT
PAPER_SAMPLER_RATE_CAP_STATE
PAPER_TRAIN_STARVATION_STATE
PAPER_TRAIN_STATE_MISMATCH
NEG_EV_PROBE_ACCEPTED
NEG_EV_PROBE_BLOCKED
NEG_EV_PROBE_EXITS
SIGNAL_RAW
RDE decision logs
ENTRY_PIPELINE_SUMMARY
ENTRY_PIPELINE_STALL
```

Relevant recent patch state:

```text
P1.1AT fixed paper sampler rate-cap reservation.
P1.1AN calibrated paper-training TP/SL geometry.
P1.1AU fixed canonical training trade count source by using LearningMonitor canonical count instead of stale learning_event metrics.
```

The Android app must be **read-only**. It must not change live/real/paper trading logic.

---

## Your Role

Act as:

```text
Senior Android telemetry architect
Senior trading-bot observability engineer
Senior Firebase data-contract designer
```

Your job is not to tune the bot. Your job is to identify and organize the metrics that should be displayed in the Android app.

---

## Hard Rules

1. Do not change trading logic.
2. Do not tune EV, RDE, TP/SL, risk, exits, or learning behavior.
3. Do not add new bot behavior unless explicitly required later.
4. Do not invent metrics as if they already exist.
5. If a metric is not directly stored but can be computed, mark it as `DERIVED` and provide the exact formula.
6. If a metric is only available in logs, mark it as `LOG_ONLY`.
7. If a metric is persisted in Firebase, identify the exact collection/document/field.
8. If source is unclear, mark it as `SOURCE_UNKNOWN` and add an investigation note.
9. Prefer stable canonical sources over noisy logs.
10. Android app must display timestamps and freshness status for every major metric.
11. All user-facing labels, tooltips, and explanations must be in Czech.
12. Avoid duplicate metrics and avoid vanity metrics that do not help operational decisions.

---

## Main Task

Analyze the repository and produce a metric catalog for Android display.

You must inspect at least these areas if present:

```text
src/services/firebase_client.py
src/services/learning_monitor.py
src/services/paper_trade_executor.py
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/realtime_decision_engine.py
src/services/signal_generator.py
src/services/market_stream.py
src/services/risk_engine.py
src/services/execution.py
src/services/execution_quality.py
src/services/adaptive_block_telemetry.py
src/services/core_flow_logging.py
scripts/p11ag_quality_audit.sh
scripts/p11ak_core_flow_viewer.sh
scripts/p11ak_core_flow_viewer_cs.sh
data/paper_open_positions.json
```

Also search the whole repo for:

```bash
rg -n "PAPER_TRAIN|LM_STATE|LEARNING_UPDATE|PAPER_EXIT|SIGNAL_RAW|ENTRY_PIPELINE|RDE|EV=|winrate|wr|pnl|drawdown|risk|quota|firebase|collection|metrics|model_state|paper_open_positions|trade_id|regime|bucket|training_bucket|cost_edge|mfe|mae|timeout|TP|SL|health|heartbeat|market_offline|stale|mismatch|anomaly"
```

---

## Required Output Files

Create these files:

```text
docs/android_metrics/METRICS_CATALOG.md
docs/android_metrics/METRICS_CATALOG.csv
docs/android_metrics/ANDROID_METRICS_SCHEMA.json
docs/android_metrics/DASHBOARD_UI_SPEC.md
docs/android_metrics/FIREBASE_READ_PLAN.md
docs/android_metrics/METRICS_GAPS_AND_RECOMMENDATIONS.md
```

If the `docs/android_metrics/` folder does not exist, create it.

---

# 1. METRICS_CATALOG.md

Create a complete Czech-language metric catalog grouped by app section.

For every metric, use this structure:

```markdown
## <Category>

### <Metric ID>
- Název v aplikaci:
- Krátký popis:
- Proč je důležitá:
- Typ: RAW / DERIVED / LOG_ONLY / HEALTH / ALERT / DEBUG
- Zdroj pravdy:
- Firebase collection/doc/field:
- Log pattern:
- Formula:
- Unit:
- Data type:
- Update frequency:
- Recommended UI:
- Priority: P0 / P1 / P2 / P3
- Freshness rule:
- Green threshold:
- Yellow threshold:
- Red threshold:
- Czech tooltip:
- Caveats:
- Implementation notes:
```

Priority definition:

```text
P0 = must show on main Dashboard
P1 = important detail view / second-level dashboard
P2 = diagnostic / advanced view
P3 = developer/debug only
```

---

# 2. METRICS_CATALOG.csv

Create a machine-readable CSV with columns:

```csv
metric_id,category,cz_label,description,priority,type,source_kind,firebase_path,log_pattern,formula,unit,data_type,refresh_rate,ui_component,green_threshold,yellow_threshold,red_threshold,tooltip_cz,caveats
```

---

# 3. ANDROID_METRICS_SCHEMA.json

Create a proposed Android/Firebase data contract.

Rules:

- Keep it read-only from Android perspective.
- Do not require Android to parse raw journal logs if a Firebase/cache summary is available.
- Prefer a normalized dashboard document if it already exists.
- If it does not exist, propose a future `android_dashboard_snapshot` document, but clearly mark it as a recommendation, not current implementation.

Include JSON sections like:

```json
{
  "dashboard": {},
  "bot_health": {},
  "market_health": {},
  "trade_summary": {},
  "open_positions": [],
  "recent_trades": [],
  "learning": {},
  "paper_training": {},
  "signal_pipeline": {},
  "risk": {},
  "alerts": [],
  "data_quality": {}
}
```

For each field include:

```json
{
  "type": "number|string|boolean|timestamp|array|object",
  "unit": "...",
  "source": "...",
  "priority": "P0|P1|P2|P3",
  "tooltip_cz": "..."
}
```

---

# 4. DASHBOARD_UI_SPEC.md

Design a meaningful Android UI structure in Czech.

The app should have max 5 main tabs:

```text
1. Dashboard
2. Obchody
3. Učení
4. Signály
5. Diagnostika
```

For each tab, specify:

- cards,
- tables,
- charts,
- filters,
- drill-down screens,
- Czech labels,
- metric tooltips,
- refresh behavior,
- empty/error/stale states.

Required Dashboard cards:

```text
Robot status
Trading mode
Last heartbeat
Market feed health
Firebase/quota state
Total trades
Winrate
Net PnL
Open positions
Last trade
Current learning health
Signal flow status
Main active warning
```

Required charts:

```text
Winrate over time
Net PnL over time
Trades per symbol
Outcome distribution
Exit reason distribution
Learning trades over time
Attribution distribution
MFE vs TP ratio
MAE vs SL ratio
Timeout rate over time
```

---

# 5. FIREBASE_READ_PLAN.md

Create a plan for reading data efficiently from Firebase.

Include:

- exact collections/documents found in code,
- estimated read frequency,
- caching strategy,
- pagination strategy for trade history,
- offline cache strategy,
- how to avoid exceeding Firestore read quotas,
- which data should be aggregated server-side instead of read raw by Android,
- recommended indexes if needed.

Respect known Firestore budget constraints:

```text
Reads: 50,000/day
Writes: 20,000/day
```

Android should not repeatedly scan large collections.

---

# 6. METRICS_GAPS_AND_RECOMMENDATIONS.md

List gaps where useful app metrics are not currently available in a clean canonical source.

For each gap:

```markdown
## Gap: <name>
- Current problem:
- User impact in Android app:
- Current workaround:
- Recommended source:
- Suggested future bot-side field/document:
- Risk:
- Priority:
- Do not implement now unless explicitly approved: yes/no
```

Examples of possible gaps to investigate:

```text
Canonical dashboard snapshot missing
Learning health not persisted cleanly
Signal pipeline counters only in logs
Recent attribution only in journal logs
Firestore vs log source mismatch
Per-symbol/regime learning summary unavailable
Open position state only in local JSON
Android app cannot safely parse systemd logs
```

---

## Metric Categories to Include

At minimum, cover these categories.

---

## A. Bot Runtime and Health

Include metrics such as:

```text
bot_status
trading_mode
service_pid
git_head
version_marker
uptime_seconds
last_heartbeat_ts
last_loop_ts
loop_latency_ms
error_count_recent
exception_count_recent
restart_count_24h
config_loaded
env_ready
secret_redaction_status
health_score
```

Important UI purpose:

```text
Can the user quickly see whether the robot is alive and running the expected version?
```

---

## B. Market Data Health

Include metrics such as:

```text
market_feed_status
last_price_tick_ts
seconds_since_last_tick
ws_connected
ws_reconnect_count
rest_fallback_active
coingecko_fallback_active
market_offline_alert_active
symbols_active_count
symbols_stale_count
per_symbol_last_price
per_symbol_tick_age
spread_pct
price_drift_pct
```

Important UI purpose:

```text
Can the user see whether prices are fresh and whether signals are based on valid market data?
```

---

## C. Firebase / Storage / Quota

Include metrics such as:

```text
firebase_ready
firestore_read_count_day
firestore_write_count_day
read_quota_pct
write_quota_pct
quota_state
quota_degraded_mode
retry_queue_size
retry_queue_oldest_age_s
last_successful_flush_ts
failed_write_count
local_spool_count
```

Important UI purpose:

```text
Can the user see whether the app and bot are reading/writing reliable data without hitting quota?
```

---

## D. Trade Summary

Include metrics such as:

```text
total_trades
closed_trades
open_positions_count
win_count
loss_count
flat_count
winrate
canonical_winrate
net_pnl_pct
gross_pnl_pct
fee_total_pct
avg_pnl_pct
median_pnl_pct
expectancy_pct
profit_factor
max_drawdown_pct
current_drawdown_pct
loss_streak
win_streak
last_trade_ts
last_trade_symbol
last_trade_outcome
last_trade_pnl
```

Important UI purpose:

```text
Can the user see whether the bot is actually successful, not only active?
```

---

## E. Open Positions

For each open position include:

```text
trade_id
symbol
side
entry_price
current_price
unrealized_pnl_pct
size_usd
entry_ts
hold_s
hold_limit_s
tp
sl
tp_pct
sl_pct
distance_to_tp_pct
distance_to_sl_pct
regime
bucket
training_bucket
paper_source
cost_edge_ok
cost_edge_bypassed
geometry_calibrated
score_raw
score_final
ev
p
rr
mfe_pct
mae_pct
max_seen
min_seen
```

Important UI purpose:

```text
Can the user inspect what is currently open and why?
```

---

## F. Trade History

For every closed trade include:

```text
trade_id
symbol
side
entry_ts
exit_ts
entry_price
exit_price
hold_s
reason
outcome
net_pnl_pct
gross_move_pct
fee_drag_pct
mfe_pct
mae_pct
touched_tp
touched_sl
near_tp
near_sl
exit_efficiency
entry_regime
exit_regime
source
bucket
training_bucket
cost_edge_ok
cost_edge_bypassed
bypass_reason
attribution
```

Important UI purpose:

```text
Can the user review exactly how trades ended and why?
```

---

## G. Signal and Decision Pipeline

Include metrics such as:

```text
raw_signals_count
accepted_signals_count
rejected_signals_count
paper_entry_attempt_count
paper_entry_success_count
reject_rate
accept_rate
last_signal_ts
last_accepted_signal_ts
last_reject_reason
reject_reason_breakdown
rde_take_count
rde_reject_count
rde_negative_ev_count
rde_score_gate_count
entry_pipeline_stall_active
entry_pipeline_idle_s
```

Per signal card:

```text
symbol
side
regime
decision
reason
score_raw
score_final
ev
p
rr
ws
coherence
thresholds
timestamp
```

Important UI purpose:

```text
Can the user see whether the bot sees opportunities and why it rejects/accepts them?
```

---

## H. LearningMonitor / Learning State

Include metrics such as:

```text
lm_total_trades
lm_count_by_symbol_regime
lm_wr_by_symbol_regime
lm_avg_pnl_by_symbol_regime
lm_ev_by_symbol_regime
lm_pnl_hist_size
lm_wr_hist_size
learning_health
sample_sufficiency
cold_start_active
warmup_progress_pct
canonical_training_trade_count
lm_update_mismatch_count
state_mismatch_count
last_lm_update_ts
last_lm_update_symbol
last_lm_update_regime
last_lm_update_outcome
```

Important UI purpose:

```text
Can the user see whether the robot is actually learning and where it has enough samples?
```

---

## I. Paper Training Diagnostics

Include metrics such as:

```text
paper_train_entry_count
paper_train_quality_entry_count
paper_train_quality_exit_count
quality_entry_mismatch
quality_exit_missing
paper_train_anomaly_count
paper_train_timeout_rate
paper_train_winrate
paper_train_avg_pnl
paper_train_avg_mfe
paper_train_avg_mae
paper_train_avg_mfe_to_tp_ratio
paper_train_avg_mae_to_sl_ratio
geometry_calibrated_count
tp_pct_avg
sl_pct_avg
cost_edge_bypass_candidate_count
cost_edge_bypass_accepted_count
cost_edge_bypass_loss_count
negative_ev_probe_accepted_count
negative_ev_probe_blocked_count
sampler_rate_cap_state_count
sampler_rate_cap_drop_count
```

Important UI purpose:

```text
Can the user see whether paper training is healthy after P1.1AT/P1.1AN/P1.1AU?
```

---

## J. Attribution and Failure Reasons

Include metrics such as:

```text
attrib_fee_dominated_move
attrib_wrong_direction
attrib_cost_edge_bypass_loss
attrib_tp_too_far_for_mfe
attrib_low_vol_timeout
attrib_near_tp_timeout
attrib_normal_win
dominant_attribution
dominant_attribution_pct
attribution_sample_count
```

Important UI purpose:

```text
Can the user see why the bot loses or times out?
```

Important rule:

```text
Do not recommend tuning unless sample_count >= 50 and one attribution > 50%.
```

---

## K. Risk and Safety

Include metrics such as:

```text
risk_budget
heat_budget
portfolio_heat
exposure_total
exposure_by_symbol
max_open_positions
open_per_symbol
open_per_bucket
drawdown_halt_active
failure_halt_active
loss_cluster_active
emergency_stop_active
meta_hard_stop_active
auditor_factor
position_size_multiplier
kelly_fraction
var_estimate
correlation_shield_active
```

Important UI purpose:

```text
Can the user see whether the bot is protected from overexposure or drawdown?
```

---

## L. Execution Quality

Include metrics such as:

```text
spread_pct
slippage_estimate_pct
orderbook_depth_score
execution_quality_factor
micro_move_score
price_drift_pct
cost_guard_active
net_edge_after_cost
fee_drag_pct
```

Important UI purpose:

```text
Can the user see whether costs/slippage are killing trades?
```

---

## M. Per-Symbol / Per-Regime Performance

For each symbol and regime:

```text
symbol
regime
trades
winrate
avg_pnl
ev
confidence
last_trade_ts
open_position
recent_signal
recent_decision
dominant_exit_reason
dominant_attribution
mfe_to_tp_avg
mae_to_sl_avg
```

Important UI purpose:

```text
Can the user see which symbols/regimes are useful or harmful?
```

---

## N. Alerts / Warnings

Include alert types:

```text
bot_offline
market_data_stale
firebase_quota_warning
firebase_quota_critical
learning_not_updating
paper_training_stalled
quality_mismatch_detected
lm_update_mismatch_detected
entry_pipeline_stall
rate_cap_stuck
too_many_timeouts
dominant_loss_reason_detected
drawdown_halt
failure_halt
secret_leak_risk
```

Each alert must include:

```text
severity: INFO / WARNING / CRITICAL
title_cz
description_cz
recommended_action_cz
source
timestamp
auto_clear_rule
```

---

## O. Data Freshness and Integrity

Include:

```text
metric_last_updated_ts
source_last_updated_ts
stale_seconds
is_stale
source_confidence
data_origin
missing_required_fields
duplicate_trade_ids
orphan_paper_exits
quality_entry_exit_match_status
lm_state_consistency_status
```

Important UI purpose:

```text
The app must show when data is stale or unreliable.
```

---

# UI Guidance

The app must be understandable for a non-technical user.

Use Czech explanations. Examples:

```text
Winrate — Kolik procent uzavřených obchodů skončilo ziskem. Nízký počet obchodů může zkreslovat výsledek.
Learning health — Ukazuje, jestli má robot dostatek vzorků pro učení. Nízká hodnota nemusí znamenat chybu, pokud je systém po restartu nebo ve fázi cold-start.
MFE — Největší nerealizovaný zisk během obchodu.
MAE — Největší nerealizovaná ztráta během obchodu.
Timeout rate — Jak často obchody skončily vypršením času místo TP/SL.
Attribution — Pravděpodobná hlavní příčina výsledku obchodu.
```

---

# Final Report Required

At the end, write a summary:

```markdown
# Summary

## Recommended P0 Dashboard Metrics
<top 15–25 metrics only>

## Metrics That Must Be Aggregated Server-Side
<list>

## Metrics Safe to Read Directly From Firebase
<list>

## Metrics Currently Only Available in Logs
<list>

## Missing Metrics / Gaps
<list>

## Android Implementation Risk
<low/medium/high with reasons>

## Next Recommended Step
<one focused step only>
```

---

## Acceptance Criteria

The output is accepted only if:

- It includes all major robot areas: health, market, Firebase, trades, positions, signals, learning, paper training, risk, attribution, alerts.
- Every metric has source, unit, type, UI priority, and Czech tooltip.
- It distinguishes RAW vs DERIVED vs LOG_ONLY.
- It proposes a Firebase read plan that avoids quota abuse.
- It avoids tuning recommendations unless clearly marked as out of scope.
- It is suitable as direct input for Android app design and implementation.
- It is detailed enough that another developer can build the app without guessing metric meanings.
---

# ADDENDUM — App Design + Codex Implementation Prompt Generator

This addendum extends the original task. In addition to creating the metric catalog and UI specification, you must also design the Android app concept and create a complex, implementation-ready prompt for Codex to build the Android application.

Use current Android best practices: Kotlin, Jetpack Compose, Material 3, adaptive layouts, clear state handling, and a read-only data layer. Material 3 is the preferred Android design system for Compose; use Material 3 components, typography, shapes, color roles, dynamic color where safe, and accessible contrast. Also design for phones first, but keep the layout adaptive for tablets/foldables using window size classes.

Important: The Android app is an observability/control dashboard. It must never execute trades, change bot config, write trading state, or modify Firebase bot data.

---

## Additional Required Output File

Add one more required output file:

```text
docs/android_metrics/CODEX_ANDROID_APP_IMPLEMENTATION_PROMPT.md
```

This file must be a complete prompt for Codex to create the Android app from the metric catalog and UI spec.

The final output set is now:

```text
docs/android_metrics/METRICS_CATALOG.md
docs/android_metrics/METRICS_CATALOG.csv
docs/android_metrics/ANDROID_METRICS_SCHEMA.json
docs/android_metrics/DASHBOARD_UI_SPEC.md
docs/android_metrics/FIREBASE_READ_PLAN.md
docs/android_metrics/METRICS_GAPS_AND_RECOMMENDATIONS.md
docs/android_metrics/CODEX_ANDROID_APP_IMPLEMENTATION_PROMPT.md
```

---

# Expanded Android Design Requirements

Create a modern Czech-language Android app design for monitoring CryptoMaster.

## Design Direction

Recommended visual direction:

```text
Modern dark trading cockpit + Material 3 cards + clear alert/status system.
```

The app should feel like a professional monitoring dashboard, not a crypto gambling app.

Use:

- dark theme as default,
- optional light theme,
- Material 3 color system,
- clear semantic colors for status only,
- dense but readable cards,
- charts with short explanations,
- small contextual help icons on technical metrics,
- timestamp/freshness badges everywhere,
- compact table rows with drill-down detail screens.

Avoid:

- neon casino style,
- too many colors,
- fake precision,
- giant vanity numbers without context,
- hiding stale data,
- mixing paper/live data without labels.

---

## Design Principles

Use these principles throughout `DASHBOARD_UI_SPEC.md` and the Codex prompt:

1. **Status first** — user must see within 5 seconds whether the bot is alive, learning, trading, and safe.
2. **Freshness visible** — every important card must show last update time and stale state.
3. **Paper/live separation** — paper training, paper trading, live, and real must be visually separated.
4. **Explain technical metrics** — every advanced metric needs Czech tooltip/help text.
5. **Decision traceability** — for every trade/signal, show why it happened or why it was rejected.
6. **No hidden warnings** — mismatches, stale data, quota issues, market feed failures, and learning stalls must surface clearly.
7. **Progressive disclosure** — Dashboard shows only essentials; diagnostics go deeper.
8. **Quota-safe UI** — Android must read summary snapshots, not scan huge Firestore collections.
9. **Safe defaults** — app is read-only; no button may trigger a trade or bot mutation.
10. **Beginner-friendly Czech labels** — avoid raw technical English unless it is an ID/log tag.

---

## Proposed App Navigation

Maximum 5 bottom tabs:

```text
1. Dashboard
2. Obchody
3. Učení
4. Signály
5. Diagnostika
```

Use a bottom navigation bar on phones. For wide screens/tablets, use a navigation rail or adaptive navigation layout.

### 1. Dashboard

Purpose: quick operational overview.

Layout proposal:

```text
Top status header
- Bot status chip: Běží / Varování / Kritické / Offline
- Trading mode chip: paper_train / paper / live / real
- Git/version chip
- Last heartbeat + freshness badge

Primary KPI grid
- Total trades
- Winrate
- Net PnL
- Open positions
- Learning health
- Last trade outcome

Operational cards
- Market feed health
- Firebase quota/storage
- Signal flow status
- Current learning progress
- Main active alert

Mini charts
- Winrate trend
- Net PnL trend
- Attribution distribution
- Timeout rate trend
```

Dashboard must include one primary warning banner if any P0/P1 alert exists.

### 2. Obchody

Purpose: open positions and closed trade history.

Sections:

```text
Open positions
- Position card per trade
- Side, symbol, entry, current, TP/SL, unrealized PnL
- MFE/MAE, hold time, bucket, regime

Trade history
- Paginated list
- Filters: symbol, side, outcome, reason, regime, bucket, date
- Sort: newest first by exit timestamp

Trade detail screen
- Entry/exit summary
- PnL breakdown: gross move, fee drag, net PnL
- TP/SL distances
- MFE/MAE timeline if available
- attribution and tooltip
- source log references if available
```

### 3. Učení

Purpose: show whether robot is actually learning and where it has enough samples.

Sections:

```text
Learning summary
- LM total trades
- canonical training trade count
- learning health
- sample sufficiency
- last LM update
- mismatch counters

Per-symbol/regime table
- symbol
- regime
- trade count
- winrate
- avg PnL
- EV
- confidence/sample sufficiency

Paper training quality
- entry/exit counts
- quality mismatch status
- average MFE/MAE
- MFE/TP and MAE/SL ratios
- timeout rate
- geometry calibration status
```

### 4. Signály

Purpose: show whether the bot sees opportunities and why it accepts/rejects them.

Sections:

```text
Signal pipeline summary
- raw signals
- RDE candidates
- accepted candidates
- paper entry attempts
- successful entries
- rejection rate
- current stall status

Signal cards by symbol
- symbol
- latest signal direction
- regime
- score_raw / score_final
- EV
- decision
- reject reason or entry source
- timestamp

Reject reason breakdown
- NEGATIVE_EV
- score gate
- cost edge
- duplicate
- rate cap
- exposure/risk gates
```

### 5. Diagnostika

Purpose: advanced troubleshooting for developer/operator.

Sections:

```text
Runtime diagnostics
- PID, uptime, git head, version marker
- restart count
- error count
- exception count

Data integrity
- quality_entry_mismatch
- quality_exit_missing
- lm_update_mismatch
- orphan exits
- stale sources

Paper-training diagnostics
- cost edge bypass flow
- negative EV probe status
- sampler rate cap state
- candidate-to-entry flow

Firebase diagnostics
- read/write quota
- retry queue
- degraded mode
- last flush

Raw debug tags
- show last N important log-derived events if available from backend snapshot
```

Diagnostics tab can be technical. The other tabs must be understandable for normal users.

---

# Visual Components Specification

In `DASHBOARD_UI_SPEC.md`, define these reusable UI components:

## StatusChip

Use for bot status, trading mode, market feed, Firebase quota, learning state.

Fields:

```kotlin
data class StatusChipUi(
    val label: String,
    val state: StatusState, // OK, INFO, WARNING, CRITICAL, STALE, OFFLINE
    val tooltip: String,
    val lastUpdated: Instant?
)
```

## MetricCard

For primary KPIs.

```kotlin
data class MetricCardUi(
    val title: String,
    val value: String,
    val unit: String?,
    val subtitle: String?,
    val trend: TrendState?,
    val status: StatusState,
    val tooltip: String,
    val freshness: FreshnessUi
)
```

## AlertBanner

For P0/P1 warnings.

```kotlin
data class AlertBannerUi(
    val severity: AlertSeverity,
    val title: String,
    val message: String,
    val recommendedAction: String?,
    val timestamp: Instant
)
```

## TradeCard

For open/closed trades.

Fields:

```text
symbol, side, outcome, entry_price, current_or_exit_price, net_pnl_pct, reason, hold_s, regime, bucket, freshness
```

## ExplainableMetricRow

For technical rows with a help icon and Czech tooltip.

## ChartCard

For time-series or distribution charts.

Required chart types:

```text
Line chart: winrate, PnL, learning count
Bar chart: trades per symbol, reject reasons, exit reasons
Donut/pie: attribution distribution, outcome distribution
Scatter/points: MFE/TP vs MAE/SL if data exists
```

If chart library is undecided, tell Codex to choose a lightweight Compose-compatible chart library or implement simple Compose Canvas charts for MVP.

---

# Color and State Rules

Use semantic status colors only. Define state meanings, not exact hex values unless the app already has a design system.

```text
OK / zelená: healthy, fresh, normal
INFO / modrá: neutral informational state
WARNING / oranžová: degraded but running
CRITICAL / červená: broken or dangerous state
STALE / šedá/žlutá: data too old
OFFLINE / šedá/červená: bot/feed unavailable
```

Important: PnL colors must not override risk colors. A profitable trade can still have a warning if data is stale.

---

# Czech UX Copy Requirements

All UI text must be Czech. Include recommended wording for:

- empty states,
- stale states,
- offline states,
- loading states,
- metric tooltips,
- error messages,
- dashboard alert banners.

Examples:

```text
Žádné otevřené pozice — Robot aktuálně nedrží žádný obchod.
Data jsou zastaralá — Poslední aktualizace je starší než povolený limit.
Učení se aktualizuje — LearningMonitor přijímá nové uzavřené obchody.
Pozor: tržní data mohou být neaktuální — poslední cenový tick je příliš starý.
```

---

# Codex Prompt Generation Task

After finishing the metric catalog and UI spec, create:

```text
docs/android_metrics/CODEX_ANDROID_APP_IMPLEMENTATION_PROMPT.md
```

This must be a **complete implementation prompt for Codex** that builds the Android app.

The Codex prompt must include:

## 1. Mission

Build a read-only Android application for CryptoMaster robot monitoring using the metric catalog and UI spec.

## 2. Expected Stack

Recommended default:

```text
Kotlin
Jetpack Compose
Material 3
MVVM or MVI-lite
Kotlin Coroutines + Flow
Firebase Firestore client OR a repository abstraction with mock data first
Room/DataStore for local cache if useful
Gradle Kotlin DSL
```

If an Android project already exists, Codex must inspect it and preserve its architecture. If no app exists, Codex should create a clean new Android project or app module.

## 3. Non-Negotiable Safety Rules

Codex must:

```text
- not modify trading bot logic,
- not add trading write actions,
- not include Firebase admin/service-account secrets in Android,
- not parse server journal logs directly from Android,
- not create buttons that mutate bot state,
- not hardcode private API keys,
- not scan large Firestore collections repeatedly,
- keep all visible UI text in Czech.
```

## 4. Required App Screens

Codex must implement at least:

```text
DashboardScreen
TradesScreen
TradeDetailScreen
LearningScreen
SignalsScreen
DiagnosticsScreen
Settings/AboutScreen
```

## 5. Required Data Models

Codex must create Kotlin models matching `ANDROID_METRICS_SCHEMA.json`, including:

```text
BotHealthUiState
MarketHealthUiState
FirebaseQuotaUiState
TradeSummaryUiState
OpenPositionUi
ClosedTradeUi
LearningSummaryUiState
PaperTrainingUiState
SignalPipelineUiState
AttributionUiState
AlertUi
FreshnessUi
```

## 6. Repository Layer

Codex must implement:

```text
CryptoMetricsRepository interface
MockCryptoMetricsRepository for local preview/testing
FirebaseCryptoMetricsRepository skeleton if Firebase paths are known
```

The app must be runnable with mock data even before Firebase is connected.

## 7. UI Components

Codex must implement reusable Compose components:

```text
StatusChip
MetricCard
AlertBanner
SectionHeader
TradeCard
ExplainableMetricRow
ChartCard
FreshnessBadge
EmptyState
StaleDataWarning
```

## 8. Design Requirements

Codex must implement:

```text
Material 3 theme
Dark theme default
Light theme support
Adaptive layout for compact/medium/expanded width
Czech labels and tooltips
Readable cards
Consistent spacing
Accessible font sizes
Clear stale/offline states
Preview composables with mock data
```

## 9. Charts

Codex must implement chart placeholders or simple MVP charts for:

```text
Winrate over time
Net PnL over time
Outcome distribution
Attribution distribution
Trades per symbol
Timeout rate over time
```

If using a library, Codex must justify it and keep dependencies minimal.

## 10. Firebase Integration Plan

Codex must:

```text
- use read-only Firestore access,
- read aggregated snapshot documents where available,
- paginate recent trades,
- cache data locally,
- show stale state when update time is old,
- avoid collection-wide scans,
- keep Firebase paths centralized in one file.
```

## 11. Testing Requirements

Codex must add:

```text
Unit tests for derived metric formulas
Unit tests for freshness/stale-state logic
Repository mock tests
Compose previews for each screen
Basic UI smoke tests if project setup supports it
```

## 12. Deliverables

Codex must produce:

```text
Working Android project/module
README_ANDROID_APP.md
Firebase setup notes
Mock data fixtures
Build/run commands
Known limitations
Next-step checklist
```

## 13. Codex Execution Style

Codex should work incrementally:

```text
Step 1: inspect repo and detect Android project presence
Step 2: create/adjust app architecture
Step 3: implement models and repository
Step 4: implement theme/components
Step 5: implement screens with mock data
Step 6: connect Firebase skeleton
Step 7: add tests/previews
Step 8: produce final report
```

Codex must prefer small safe commits and must not touch Python bot trading files unless only reading them.

---

# Additional Acceptance Criteria

The expanded task is accepted only if:

- `DASHBOARD_UI_SPEC.md` contains concrete screen design, not only a metric list.
- The design uses Material 3 / Jetpack Compose concepts.
- The design includes Czech UI copy and tooltips.
- The design includes loading, empty, stale, warning, critical, and offline states.
- `CODEX_ANDROID_APP_IMPLEMENTATION_PROMPT.md` is detailed enough that Codex can create the Android app without asking for architecture decisions.
- Codex prompt explicitly forbids bot trading logic changes and Firebase write actions.
- Codex prompt includes mock data mode so the app can be built before Firebase integration is complete.
- Codex prompt includes tests and previews.

