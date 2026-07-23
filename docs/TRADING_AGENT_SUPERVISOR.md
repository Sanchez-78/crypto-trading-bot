# Autonomous PAPER trading agents

## Purpose

The agent runtime monitors three independent concerns without granting any
component direct exchange or configuration access:

1. price-feed health and short-horizon market state;
2. trading and learning activity;
3. bounded, evidence-based PAPER entry policy.

The implementation lives in
`src/services/trading_agent_supervisor.py`. It is deterministic application
code, not an unconstrained LLM loop.

## Topology and ownership

```text
market_stream ──tick──> MarketStateAgent ──observation──┐
                                                       │
durable trades + learning ──> TradingHealthAgent ──────┼─> StrategyTuningAgent
                                                       │       │ proposal only
                                                       │       v
                                                       └─> TradingAgentSupervisor
                                                               │ sole writer
                                                               v
paper_training_sampler <── pause / entry quota policy ─────────┘

dashboard_read_model <── persisted supervisor state (read-only)
```

| Component | Inputs | Output | Allowed tools/state | Forbidden |
| --- | --- | --- | --- | --- |
| `MarketStateAgent` | Per-symbol price and tick time, expected symbols | freshness, coverage, stale symbols, broad regime | bounded in-memory deques | orders, files, policy writes |
| `TradingHealthAgent` | durable closes, open positions, learning snapshot | trading/learning activity and rolling evidence | in-memory observations | orders, strategy mutation |
| `StrategyTuningAgent` | the two observations and current policy | pure proposal | calculation only | disk, env, execution |
| `TradingAgentSupervisor` | proposals, runtime mode and safety flags | validated policy, audit trail, dashboard state | one atomic JSON state file | `.env` edits, order APIs, live-real changes |
| `paper_training_sampler` | current effective policy | accept/reject of a PAPER training candidate | current candidate only | size increase, live execution |

There is one write authority: `TradingAgentSupervisor`. The specialist agents
cannot call execution functions or edit configuration.

## Handoffs

### Market tick handoff

- Trigger: every validated `market_stream` tick.
- Payload: `symbol`, positive finite `price`, Unix `timestamp`.
- Contract: O(1), in-memory only; no disk or analysis on the stream thread.
- Failure: log at debug level and leave trading flow intact. Missing ticks are
  detected by the next supervisor cycle.

### Observation handoff

- Trigger: one supervisor cycle, normally every 60 seconds.
- Payload: immutable dictionaries produced from durable trade state, current
  open positions, learning metrics and per-symbol tick history.
- Timeout model: no network calls are made. An exception counts as a failed
  cycle.
- Failure: unchanged policy is retained. Three consecutive failures open the
  circuit breaker for 10 minutes by default.

### Strategy proposal handoff

- Trigger: both monitoring observations are available.
- Payload: target quota `0.50..1.00`, entry-pause boolean, reason, urgency and
  evidence snapshot.
- Acceptance:
  - PAPER mode and all real-order flags must be safe;
  - normal changes require the same proposal twice;
  - recovery from a pause requires three confirmations;
  - a critical stale-feed pause can apply immediately;
  - changes are limited to `0.25` quota per revision;
  - later risk restoration requires cooldown plus new closed-trade evidence.
- Rejection/timeout: the current policy remains active and the decision is
  persisted for diagnosis.

### Candidate-policy handoff

- Trigger: a PAPER training candidate reaches the sampler.
- Payload: symbol, training bucket and original `size_mult`.
- Result: accept unchanged size, quota-reject, or pause-reject.
- Important: quota sampling changes entry frequency only. It never increases or
  decreases the accepted position size.

## Safety invariants

- Automatic application is permitted only in `paper_live`, `paper_train` or
  `replay_train`.
- Any truthy `ENABLE_REAL_ORDERS`, `LIVE_TRADING_CONFIRMED` or
  `REAL_TRADING_ENABLED` flag blocks policy mutation and restores the effective
  baseline.
- The only controls are `pause_new_entries` and
  `paper_entry_quota_multiplier`.
- Quota is always clamped to `0.50..1.00`; automatic logic cannot increase
  exposure above baseline.
- Agents cannot change leverage, TP/SL, symbols, capital, order size, credentials
  or environment variables.
- Corrupt or missing state is replaced by the safe baseline.
- State writes are atomic and the audit log is bounded to 50 records.
- Existing open positions are never force-closed by this subsystem.
- A critical price feed pauses new PAPER entries; it does not close positions
  using a cached price.

## Policy evidence

Automatic performance tuning is intentionally conservative:

- at least 200 lifetime samples;
- at least 20 samples in the recent window;
- profit factor below `0.80` or negative expectancy reduces quota to `0.75`;
- profit factor below `0.50` or expectancy at/below `-0.15` targets `0.50`;
- restoration to `1.00` requires profit factor at/above `1.05`, positive
  expectancy, the policy cooldown, and at least 20 new closed trades.

These thresholds only govern entry frequency in PAPER training. They do not
claim that a strategy is profitable.

## Configuration

All settings default to disabled/safe values in `.env.example`.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `TRADING_AGENT_SUPERVISOR_ENABLED` | `false` | start the supervisor loop |
| `TRADING_AGENT_AUTO_APPLY` | `false` | permit bounded PAPER policy application |
| `TRADING_AGENT_INTERVAL_S` | `60` | monitoring interval |
| `TRADING_AGENT_PRICE_STALE_AFTER_S` | `90` | per-symbol price freshness threshold |
| `TRADING_AGENT_MARKET_WARMUP_S` | `120` | startup grace before offline-feed pause |
| `TRADING_AGENT_HIGH_VOL_BPS` | `15` | median tick move for high-volatility label |
| `TRADING_AGENT_TRADE_STALL_AFTER_S` | `7200` | no-close activity threshold |
| `TRADING_AGENT_LEARNING_STALL_AFTER_S` | `7200` | unchanged learning count threshold |
| `TRADING_AGENT_MIN_LIFETIME_SAMPLES` | `200` | lifetime tuning evidence |
| `TRADING_AGENT_MIN_TUNING_SAMPLES` | `20` | recent tuning evidence |
| `TRADING_AGENT_MIN_NEW_TRADES` | `20` | evidence required after a policy revision |
| `TRADING_AGENT_POLICY_COOLDOWN_S` | `3600` | minimum normal revision interval |
| `TRADING_AGENT_CIRCUIT_FAILURES` | `3` | failures before circuit opens |
| `TRADING_AGENT_CIRCUIT_COOLDOWN_S` | `600` | circuit-open duration |
| `TRADING_AGENT_STATE_FILE` | production backup path | optional state-file override |

The production default state path is
`/opt/cryptomaster/server_local_backups/trading_agent_supervisor_state.json`.
The canonical dashboard API exposes its read-only snapshot as
`agent_supervisor`.

## Rollout and rollback

1. Deploy code with both feature flags false.
2. Enable `TRADING_AGENT_SUPERVISOR_ENABLED=true` to observe proposals only.
3. Verify price coverage, trading timestamps and state freshness.
4. In PAPER mode only, enable `TRADING_AGENT_AUTO_APPLY=true`.
5. Watch policy revisions and quota/pause decisions in the dashboard and
   service journal.

Fast rollback is `TRADING_AGENT_AUTO_APPLY=false`, followed by a bot service
restart. Full rollback also disables `TRADING_AGENT_SUPERVISOR_ENABLED`.
Neither rollback requires changing or closing existing paper positions.
