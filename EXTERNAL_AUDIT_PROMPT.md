# CryptoMaster HF-Quant 5.0 — External Audit Prompt

> **Role for the auditor:** Senior trading-systems + backend + security engineer.
> **Objective:** Independent, adversarial, end-to-end audit of a crypto **paper-trading** bot running on a Hetzner VPS — correctness, safety, security, trading-edge validity, observability, and deployment integrity.
> **Repository:** `Sanchez-78/crypto-trading-bot` (GitHub, public).
> **Absolute constraint:** This bot must **NEVER** be switched to live trading. Do not propose, enable, or test any live-order path. All work is on paper (`TRADING_MODE=paper_live`, live orders quadruple-gated). Read-only wherever possible; any write/restart must be reversible and gated.

---

## 0. TL;DR of what you are auditing

A Python HFT-style crypto bot ("CryptoMaster HF-Quant 5.0") that:
- Ingests Binance market data over WebSocket (`market_stream.py`) → `event_bus` → signal generation → Bayesian/EV decision engine → **simulated** (paper) order execution → learning/calibration → Firestore + local SQLite persistence.
- Currently runs a **mean-reversion strategy** ("DEV_FADE"): fades trailing 15-min price deviations ≥ 25 bps on 7 fixed symbols.
- Is operated **entirely from a mobile phone with no shell** — every server interaction happens through **GitHub Actions workflows** (SSH with pinned host key). There is no interactive ops access.
- Serves a **Flask dashboard/API on port 5001** consumed by an external Android app.

Your job: verify it does what it claims, find what's broken or unsafe, and validate whether the trading edge is real or an artifact.

---

## 1. Runtime environment & how to connect to the server

### 1.1 Host
- **Provider:** Hetzner Cloud VPS (4 GB, `ubuntu-4gb-nbg1-1`), Debian 12 (Python 3.12 system, PEP 668 externally-managed).
- **Public IP:** `78.47.2.198` (visible in the Android app; the dashboard API is at `http://78.47.2.198:5001/api/dashboard/metrics`).
- **Project path on server:** `/opt/cryptomaster` (real). A symlink `/opt/CryptoMaster_srv → /opt/cryptomaster` exists because several unit files and scripts hard-code the `CryptoMaster_srv` path. Repo owner on disk: user `cryptomaster`; systemd services run as **root**.
- **Git:** repo cloned on the server, `origin` = the GitHub repo over HTTPS. Systemd runs deploy as root; note the historical "dubious ownership" (exit 128) class of bug — verify `HOME=/root` is exported so `git` reads `/root/.gitconfig` (`safe.directory '*'`).

### 1.2 Connection model (IMPORTANT — there is no direct human SSH in normal ops)
All server access is mediated by **GitHub Actions `workflow_dispatch` workflows** under `.github/workflows/`. They SSH in using repository **secrets** (never printed):
- `HETZNER_HOST` — server IP/hostname
- `HETZNER_USER` — SSH login user (root-capable)
- `HETZNER_SSH_KEY` — private key (PEM/OpenSSH)
- `HETZNER_PROJECT_DIR` — `/opt/cryptomaster`
- `HETZNER_SERVICE_NAME` — `cryptomaster`
- (optional) `HETZNER_PORT` — default 22

Host-key handling: every workflow pins the host key via `ssh-keyscan` into `known_hosts` and uses `StrictHostKeyChecking=yes -o BatchMode=yes`. There is **no** blind `AutoAddPolicy`.

> **To perform hands-on server checks**, the repo owner must provide you EITHER (a) temporary read-only SSH credentials out-of-band, OR (b) you extend/execute the existing read-only observability workflow (below). **Do not** request the secret values in plaintext through insecure channels; prefer running the existing workflows and reading their artifacts.

### 1.3 The workflows you will actually use
- **`hetzner-fetch-health.yml`** — READ-ONLY observability. SSHes in and publishes artifacts: `latest_health.md/json`, `latest_deploy_status.md/json`, sanitized `log_tail_sanitized.txt`, `service_status.txt`, `quota_forensics.txt`, `deploy_diagnostics.txt`, `git_failure_repro.txt`, `trading_metrics.txt`, `dashboard_metrics.json`, `cache_sqlite_probe.txt`, `close_path_forensics.txt`, `restart_forensics.txt`, `edge_analysis.txt`, `mfe_distribution.txt`. **Start here.** Trigger it (`workflow_dispatch`) and download the artifact `cryptomaster-health-<N>`.
- **`hetzner-repair-autodeploy.yml`** — `git reset --hard origin/main`, install systemd units, refresh dashboard venv + restart, one deploy/audit cycle. Hard-blocks live flags. Use to (re)deploy `main`.
- **`hetzner-one-time-install.yml`** — installs the autodeploy timer (idempotent).
- **`hetzner-set-*.yml`** (`paper-size`, `paper-tp`, `fade-sides`, `apply-symbol-blacklist`) — each edits **exactly one** `.env` key, hard-blocks live flags, auto-rollbacks on failed restart. These are the ONLY sanctioned way to change runtime params.
- **`deploy.yml`** — triggers on push to `main` (paths-filtered to `src/**`, `bot2/**`, `start.py`, requirements, `config.py`); `git reset` + restart `cryptomaster`. **Audit the paths filter** — a prior bug restarted the bot on every merge, killing open positions.

### 1.4 systemd units (on server, under `/etc/systemd/system/`)
- `cryptomaster.service` — main bot, `ExecStart=/usr/bin/python3 -u /opt/cryptomaster/start.py`, `Restart=always`. Has several drop-ins: `10-paper-only.conf`, `20-real-trading.conf`, `30-phase2-real-trading.conf`, `emergency.conf`, `override.conf`, `zz-force-paper-only.conf`, `zz-swing-horizon.conf`. **AUDIT these drop-ins** — the `*-real-trading.conf` files are a red flag; confirm `zz-force-paper-only.conf` (alphabetically last → wins) actually forces paper and that no real-order env is set.
- `cryptomaster-dashboard.service` — Flask on `0.0.0.0:5001` via `start_flask_dashboard.py` using venv `/opt/dashboard_venv` (built from `requirements-dashboard.txt`). Per `CLAUDE.md`, run Flask **directly** (no Gunicorn).
- `cryptomaster-autodeploy.{service,timer}` — 2-hour oneshot deploy/audit loop (`scripts/hetzner_paper_train_deploy_and_audit.sh`), runs as root with `ExecStartPre` git `safe.directory`.

### 1.5 State & data stores
- **Firestore** (Firebase, free tier): trades (`trades_paper`), metrics, learning state, `app_metrics/latest`, `dashboard_snapshot`. Quota: 50k reads / 20k writes per day, resets **07:00 UTC**. Local-first caching in `runtime/firebase_cache.sqlite`.
- **`local_learning_storage/cache.sqlite`** — primary close sink (`closed_trades` table: trade_id, symbol, side, entry/exit ts+price, pnl_usd, pnl_pct, win, exit_reason, regime, mfe, mae). Gitignored (deploy no longer wipes it).
- **`server_local_backups/paper_adaptive_learning_state.json`** — durable rolling window (rolling20/50/100, lifetime_n/pf/expectancy, segment_weights).
- `data/paper_open_positions.json` — open positions, hydrated on restart.

---

## 2. Architecture & code map (verify each claim)

```
Binance WS ─▶ market_stream.py ─▶ event_bus.py ─▶ signal_generator.py
   ─▶ realtime_decision_engine.py (Bayesian calibration + EV gating + buckets)
   ─▶ trade_executor.py ─▶ paper_trade_executor.py (position lifecycle, TP/SL/TIMEOUT)
   ─▶ learning_monitor.py / paper_adaptive_learning.py (calibration, rolling metrics)
   ─▶ firebase_client.py (Firestore + quota) + local_persistent_cache.py (cache.sqlite)
   ─▶ app_metrics_contract.py ─▶ dashboard_web.py (Flask :5001 → Android app)
```

Key modules to read: `src/services/{signal_generator,realtime_decision_engine,paper_trade_executor,trade_executor,firebase_client,learning_monitor,paper_adaptive_learning,local_persistent_cache,dashboard_web,app_metrics_contract,market_stream}.py`, `src/core/{runtime_mode,event_bus,self_heal,anomaly}.py`, `bot2/main.py`, `start.py`.

---

## 3. Audit scope — what to verify (ranked)

### A. Safety / no-real-trading (highest priority)
1. Prove real orders are impossible in the current config. `live_trading_allowed()` (`src/core/runtime_mode.py`) must require ALL of: `TRADING_MODE=live_real` AND `ENABLE_REAL_ORDERS=true` AND `LIVE_TRADING_CONFIRMED=true` AND `PAPER_EXPLORATION_ENABLED=false`. Confirm none are set on the server (`.env` + systemd drop-ins, esp. `20-/30-*real-trading.conf`).
2. Audit `binance_client.py` and any order-submission path: confirm every real-order call site is guarded by `check_live_order_guard()`; look for any bypass.
3. Confirm the `hetzner-set-*` and `deploy`/`repair` workflows cannot flip a live flag; verify their `.env` gates.

### B. Trading-edge validity (is the profit real?)
4. The bot shows high win-rate (~60–66%) but **Profit Factor hovers ~1.0** and lifetime P&L is slightly negative. Independently reproduce PF/WR from `cache.sqlite` (segment by side/symbol/regime/hour). **Do not trust global WR.**
5. **Cost model:** `PAPER_FEE_PCT=0.0015` (15 bps) + `PAPER_SLIPPAGE_PCT=0.0003` (3 bps) = ~18 bps round-trip vs a realistic futures-maker ~4 bps. Captured DEV_FADE reversion is only ~10–25 bps. Assess whether the edge survives realistic costs and whether the paper cost is over- or under-stated (do NOT recommend lowering it just to flatter results — flag the honest number).
6. **Directional bias:** side-tracked data showed BUY-fades ~72% WR/+0.17 vs SELL-fades ~55% WR/−0.23. A `buy_only` experiment (`PAPER_FADE_SIDES=buy_only`) is currently deployed. Evaluate overfitting/regime risk (data is from a single uptrend; a downtrend likely inverts it). Recommend a robust rollback rule.
7. TP/SL geometry: `PAPER_TP_ZONE_BPS` (~60 effective) vs `PAPER_SL_ZONE_BPS` (~80) → 1:0.75 reward:risk, and 100% of exits are TIMEOUT. Verify TP/SL are actually reachable and whether geometry is mis-set. `MIN_TP_PCT=0.0020` floor.
8. `DEV_FADE` validation claims (`signal_generator.py` comments): gross +7.4/+10.5 bps, DA ~63%, net +3.4/+6.5 bps at 4 bps cost. Stress-test these claims — sample size, look-ahead, survivorship, regime dependence.

### C. Learning-loop correctness
9. Confirm `LEARNING_UPDATE ok=True` fires on closes (a prior bug: the close-path learning hooks gated on `paper_source=="training_sampler"` while P0.3C rewrote it to `"paper_evidence_collection"`, making learning dead code — fixed 2026-07-16). Verify the fix and that no other close path is orphaned (`normal_rde_take`, `paper_adaptive_recovery` are a **known latent gap** — still unlearned).
10. Verify D_NEG_EV_CONTROL / TIMEOUT_NO_PRICE trades are correctly excluded from canonical learning; no double-learning.
11. Confirm learned state actually changes admission behavior (causality), segmented — not just global counters.

### D. Firebase quota & resilience
12. Verify no per-tick Firestore reads/writes; caching effective; the `quota_429` degradation now clears at the 07:00 UTC reset (prior bug: blind 24h window kept learning dead). Check `_record_read` attribution logging.
13. Confirm fail-closed behavior on 429/quota-exhausted (cache reads, bounded retry queue, no crash).

### E. Dashboard / Android API (security + correctness)
14. **SECURITY (high):** dashboard binds `0.0.0.0:5001` with **NO authentication** — every endpoint is world-readable, and some routes shell out to `journalctl`/subprocess. Assess exposure (is port 5001 firewalled at the Hetzner level?), info disclosure (full strategy/edge/PF), and DoS surface. Recommend auth + bind/firewall.
15. **Correctness:** headline `win_rate_pct`/`profit_factor` must reflect the intended window. A prior bug sourced PF from lifetime while WR came from the learning rolling window (app showed red 41% while recent form was 62%); fixed to a cache-sourced rolling-100 headline. Verify consistency across `/api/dashboard/metrics`, `/api/trades/recent`, exit distribution; verify never-500 degraded JSON; verify Czech labels + ms-precision ISO8601 UTC timestamps match the Android contract (`.claude/skills/android-dashboard-contract`).
16. `side`/`pnl_pct` persistence: cache.sqlite historically lost trade direction (legacy NULL `side`), causing sign inversion on the displayed pnl for shorts; verify the fix and the legacy-row heuristic.

### F. Ingestion / runtime robustness
17. `market_stream.py`: WebSocket reconnect churn (Binance slow-consumer disconnects) was caused by a per-tick log flood; verify the `ping_interval=180/ping_timeout=60` keepalive and that debug floods (`P0_5*`, `TP_SL_EVAL`) are env-gated OFF by default.
18. `SELF_HEAL`/`EMERGENCY_MONITOR` (`src/core/self_heal.py`, `anomaly.py`, `emergency_health_monitor.py`): verify LEARNING_STALL detection isn't producing false alarms (a prior log showed an epoch value printed as a duration).
19. Env-gate inventory: enumerate every env var that alters trading (`PAPER_DEVIATION_FADE`, `PAPER_DEV_GATE_BPS`, `PAPER_FADE_SIDES`, `PAPER_INVERT_SIGNAL`, `SIGNAL_INVERT_TEST`, `PAPER_SYMBOL_BLACKLIST`, `PAPER_TP_ZONE_BPS`, `PAPER_SL_ZONE_BPS`, `PAPER_POSITION_SIZE_USD`, `PAPER_MAX_POSITION_AGE_S`, sizing/exposure caps). **Flag the `SIGNAL_INVERT_TEST=1` + `PAPER_FADE_SIDES=buy_only` double-flip footgun** (executes the anti-edge side).

### G. Deployment / ops integrity
20. Verify the deploy/autodeploy chain: `deploy.yml` paths filter, `hetzner-repair-autodeploy.yml`, the 2h timer, and that server-side pytest is optional (Debian 12 lacks deps). Confirm the git `safe.directory`/`HOME=/root` fix.
21. Confirm the `set-*` workflows' `.env` edits are atomic-enough / fail-safe and truly reversible; check `.env.bak.*` handling.
22. Confirm no secrets leak into logs/artifacts (the observability workflow redacts key/token/password patterns and https-token remotes — verify the redaction regexes are sufficient).

---

## 4. Method

1. **Read the repo** at `main` first; build the module map; note version/patch history in `CLAUDE.md` and the `*_REPORT.md`/`PATCH_*.md` files (there are many — treat as claims to verify, not ground truth).
2. **Pull live evidence** by running `hetzner-fetch-health.yml` and reading its artifacts. Cross-check code claims against runtime (e.g., is learning actually firing? are only BUY closes appearing under `buy_only`? is PF really >1?).
3. **Reproduce the numbers** yourself from `cache.sqlite` (via the read-only probe) — never trust the dashboard headline alone.
4. **Separate observed facts from hypotheses.** Cite `file:line` and exact log lines / artifact fields for every finding.
5. **Rank findings** by severity (Critical/High/Medium/Low) with a concrete, minimal, reversible remediation for each. For any trading-core change, require an evidence-first + independent-review gate and a rollback trigger.

---

## 5. Known findings from the prior internal session (starting point — verify & extend)

These were found and (mostly) fixed already; confirm they hold and look for regressions or adjacent issues:
1. `deploy.yml` restarted the bot on **every** push → open positions killed before their 15-min timeout → learning starved, dashboard list stale. Fixed with a paths filter. *(Verify the filter is complete.)*
2. Close-path learning hooks were **dead code** since the P0.3C `paper_source` rewrite → `LEARNING_UPDATE ok=True` = 0 for a long period. Fixed by widening the gate to `paper_evidence_collection`. *(Latent gap: `normal_rde_take`/`paper_adaptive_recovery` still unlearned.)*
3. Firebase `quota_429` degradation used a blind `now+24h` window instead of clearing at the 07:00 UTC reset → learning dead up to a full day. Fixed.
4. systemd didn't set `$HOME` → `git` couldn't read `/root/.gitconfig` → "dubious ownership" exit 128 on every timer cycle since ~May. Fixed with `HOME=/root` + `safe.directory '*'`.
5. Dashboard headline mixed **lifetime** PF with **rolling** WR → app showed a false red 41%/0.38 while recent form was 62%. Fixed to a cache-sourced rolling-100 headline; lifetime kept separate.
6. cache.sqlite lost `side` → sign-inverted pnl for shorts on the displayed list. Fixed with a `side` column + migration + legacy heuristic.
7. P0.5/TP_SL_EVAL **log floods** (~75+ lines/s) caused WS slow-consumer disconnects and unusable journals. Env-gated OFF.
8. **Thin edge:** captured reversion ~20 bps ≈ simulated cost ~18 bps → PF ~1.0. **Do not "fix" by lowering simulated costs** — that would be self-deception.
9. **Directional bias:** SELL-fades are anti-edge in the current uptrend; `buy_only` experiment is live and under measurement. Regime risk is the open question.
10. **Security:** dashboard `:5001` has no auth. Unaddressed — treat as a High finding to design properly.
11. `PAPER_SYMBOL_BLACKLIST=BNBUSDT,XRPUSDT` applied (0/72 and 1/65 wins historically); DOTUSDT was held out.

---

## 6. Deliverable

A written audit report with:
- **Executive summary** (is it safe? is the edge real? top 5 risks).
- **Findings table** (severity, `file:line` / artifact evidence, failure scenario, minimal reversible fix).
- **Trading-edge verdict** — reproduced PF/WR by segment, with the honest cost-adjusted expectation and a statement on regime dependence / overfitting of the `buy_only` bet.
- **Security section** — dashboard exposure, secret handling, deploy integrity.
- **Explicit confirmation** that no real-order path is reachable in the current config, and a list of exactly which flags/files would have to change to enable live (so they can be monitored).

**Do not enable live trading. Do not lower simulated costs to inflate results. Cite evidence for every claim.**
