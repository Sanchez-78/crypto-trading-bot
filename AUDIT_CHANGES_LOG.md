# CryptoMaster — Audit Changes Log (continuation handoff)

---

## ⭐ ROUND 4/5 STATUS (2026-07-18) — authoritative; supersedes everything below

> **Deployed SHA on server:** `1eba962` (autodeploy 2h). **REAL trading = NO-GO (unchanged).** Paper-only, **trading PAUSED** (`PAPER_SYMBOL_BLACKLIST` = all 7 symbols → `signal_generator.py:682` returns → 0 new entries), `open_positions=0`.
> Pairs with `EXTERNAL_AUDIT_PROMPT_v5.md` (+ external report v5, remediation below).

### Round-4 remediation
| Finding | R4 verdict | R5 status | PR | Gate |
|---------|-----------|-----------|----|----|
| **F10** firewall | injection (HIGH) | anti-injection validation (enum + `ipaddress` + port allowlist) before SSH; fail-closed rollback (never `ufw delete deny`); default port **5000** (5001 = LIVE API untouched) | **#77 merged** | reviewer APPROVE (LOW) + trading-safety SAFE |
| **F2/F3** reset-before-gate | REJECT | `git reset --hard` + restart now AFTER hold + zero-position gates; decided from fetched SHAs before any working-tree mutation; docs-only sync stays allowed | **#79 open** | reviewer gate in progress; `bash -n` OK, 22/22 static tests |
| **health CSV** | (new) | read-only full `closed_trades` CSV dump for offline E1–E4 | **#78 merged** | self-verified (read-only, non-trading) |

### Round-5 core finding — negative expectancy + E1–E4 blocked
- **All 1021 local closes are `TIMEOUT`** (TP ~54bps / SL never hit). WR 31% (win col), net −0.9164 usd. Clean `pnl_pct` subset (162): **PF 0.924**, −18.77 bps/trade after 18bps cost.
- Segments: `BULL_TREND` 25.8% vs `BEAR_TREND` 46.3%; BNB 0/72, XRP 1/65. → DEV_FADE has no edge in current regime.
- **E1–E4 cannot run:** excursion columns populated on only **6/1021** rows (F8 population just started). Pause halts further accumulation → catch-22. Auditor to decide data-collection path / F8b priority / strategy fate (`EXTERNAL_AUDIT_PROMPT_v5.md` §6).

### Runtime (health-536, server `1eba962`)
- F2/F3 mechanism live: `repo=ready=boot=1a72e42`, `deployed=5a26731` (marker lag), `deploy_hold absent`, owner uid 999 (non-root). Code-impact gate correctly skipped restart for workflow-only #77/#78. Pause confirmed (mode neutral, 0 entries).

### Round-5 external report (`CryptoMaster_EXTERNAL_AUDIT_REPORT_v5`) — remediation
> **Cost correction:** `closed_trades.pnl_pct` is already cost-inclusive (net) — the clean 162-row subset is **−0.77 bps/trade AFTER costs** (not −18.77). PF 0.924 < 1; still no edge. Recent windows PF 0.27–0.43.

| v5 finding | verdict | remediation | PR | Gate |
|-----------|---------|-------------|----|----|
| **F10 external probe** | REOPENED (`curl -f /healthz` mis-reads 404 as refused) | raw **TCP-connect** probe, IPv4+IPv6 separately, fail-closed | **#81 merged** | reviewer APPROVE |
| **Blacklist workflow** | NEW HIGH (raw `SYMBOLS`→SSH/.env RCE; restart w/o gate) | validate action enum + exact symbol allowlist **for every action** (revert/status RCE closed); zero-position gate (UNKNOWN=refuse) before restart | **#81 merged** | reviewer REJECT→fix→APPROVE (executable injection test) |
| **F2/F3-r3 (#79)** | REJECT (4 scenarios) | **superseded by operator-approval model:** read-only timer (fetch+staging-worktree-compile+notify, never reset/restart); new `hetzner-deploy-apply.yml` gated switch (staging compile→zero-position UNKNOWN→hold→switch→rich READY→rollback), PLAN dry-run | **#82** | reviewer REJECT (dead-svc OK clobber)→fix→**APPROVE** |
| **Port 5000 dashboard** | disable | gated behind `LEGACY_DASHBOARD_5000_ENABLED` (default OFF); :5001 Flask untouched | **#83** | self-verified |
| **F8b recorder** | GO (mandatory for E1–E4) | `shadow_excursion_recorder.py`: in-memory 1s directional path + first-crossing ladder, persist once to separate sqlite (`shadow_*` tables), default-OFF, no trading side effects; thread-safe persist + TTL sweep | **#84** | reviewer APPROVE + integration fixes |

**Chain:** #77 (F10-r2) → #78 (health CSV) → #80 (v5 prompt) → **#81 (F10-r3 + blacklist) merged** → #82 (deploy model) → #83 (port 5000) → #84 (F8b recorder) — #82–#84 await operator merge.

**Still operator/data/time-gated (v5 §10–15, NOT autonomous):** merge #82–#84 + deploy via `hetzner-deploy-apply.yml`; wire F8b into per-tick path (follow-up PR, runtime-verified) + enable `PAPER_DATA_COLLECTION_ONLY=1`; collect ≥500 shadow observations / ≥14 days / ≥100 per segment; offline E1–E4 walk-forward (OOS PF ≥1.20, expectancy >0 after 18bps, stress 22–25bps, no symbol >40%); then ONE gated paper forward test. **REAL = NO-GO.**

---

## ⭐ ROUND 3 STATUS (2026-07-17) — superseded by Round 4/5 above

> **Deployed SHA on server:** `main` HEAD (autodeploy timer, 2h). **REAL trading = NO-GO (unchanged).** Paper-only (`TRADING_MODE=paper_train`), 0 open positions, `live_trading_allowed=false`, `zz-force-paper-only.conf` active.
> Pairs with `EXTERNAL_AUDIT_PROMPT_v3.md` and external reports `CryptoMaster_EXTERNAL_AUDIT_REPORT_v2` / `_v3`.

### External-audit remediation status (per the Round-3 report)
| Finding | Round-3 verdict | Remediation |
|---------|-----------------|-------------|
| **F1** unguarded real Binance order path | CLOSED STATICALLY (runtime sign-off pending fresh artifact) | #69 — `market_order` fail-closed via `check_live_order_guard()` before any HTTP |
| **F2/F3** deploy/process SHA drift + unsafe restart | was PARTIAL → **round-2 fixes done** (this branch) | #71 + follow-up: decide restart off **READY** marker (written post-init), fail-closed on missing marker, root-owned `.deploy_hold` + TTL, **fail-closed** position parse, `deployed_bot_sha` only after `is-active`+READY convergence |
| **F4** auth bypass when security ON | CLOSED STATICALLY | #70 |
| **F5** pipeline mode no-op | was PARTIAL → **round-2 fix done** (this branch) | unknown/typo mode now **fail-closed** (`assert_supported_mode`: only unset/off/shadow start) |
| **F9** audit log stale | REOPENED → **this update** | log now reflects PR #69–#71 + round-2 residual fixes |

### Round-3 remediation — done since (all reviewer-gated)
- **F8 (#73)** — `trade_excursion.py`: persist gross MFE/MAE (fraction+pct+bps, side-aware) + `time_to_mfe/mae` (extreme ordering = first-order TP-before-SL proxy) + `favorable_first()`. Additive cache columns. Observability only; reviewer proved max/min values identical over 200k tick sims. **F8b (full 1s price-path table) deferred** — global-extreme timestamps give first-order ordering; the per-candidate-level path is the refinement.
- **F6/F7 (#74)** — one explicit `headline` window (wins/losses/flats/WR/net all same window) + dual PF (`profit_factor_pct_basis`/`_usd_basis`). Browser chart reads `data.headline.*` (no more lifetime×recent-WR; FLAT its own slice). Additive — Android contract PRESERVED (android-contract gate PASS). Degraded envelope carries a zeroed headline.

### Still OPEN (operator- or snapshot-gated)
- **F10 (Med)** — firewall workflow needs external remote-probe + `ufw active` + IPv4/IPv6 + rollback. GO for prep, **APPLY needs operator**.
- **F11 (Med, runtime-only)** — single-step `lifetime_n` proof from full `close_path_forensics.txt` — **needs a fresh server artifact** (`hetzner-fetch-health.yml`).
- **F1 runtime sign-off** — statically CLOSED; the absolute "no runtime path reaches real order submission" sentence needs a fresh artifact confirming `EXECUTION_ENGINE_ENABLED != 1` + live flags false.
- **Dashboard security enable (`DASHBOARD_SECURITY_ENABLED=1`) / PR6 Phase B / any edge change** — all **NO-GO** now; see `EXTERNAL_AUDIT_PROMPT_v3.md` §11 for preflight/criteria. Edge E1–E4 offline counterfactual is now *unblocked* by F8 (needs ≥100–200 post-deploy closes carrying the excursion data).

### MASTER IMPLEMENTATION PROMPT — all merged (each reviewer-gated)
| PR | Finding | Status |
|----|---------|--------|
| #62 | P1.5 deterministic **dispatch-only** deploy + reversible V5 teardown | ✅ merged |
| #63 | P2 per-tick log throttle + fail-closed **double-flip env guard** | ✅ merged |
| #64 | P2.9/P1.8 canonical outcome + PnL-units contract (golden-locked) | ✅ merged |
| #65 | P1.7 one dashboard read-model (never-500, dead sources removed) | ✅ merged |
| #66 | P1.6 dashboard auth + localhost bind + non-root hardening | ✅ merged |
| #67 | P0.4 canonical close pipeline — **SHADOW mode, default off** | ✅ merged |

> The Round-2 incident (#68 ship-dark dashboard restore) and the full 6-PR master implementation are covered above / in `EXTERNAL_AUDIT_PROMPT_v3.md`.

### Runtime (snapshot `health-526`, honest)
- **Safety:** paper_train, live gated, 0 positions. ✅
- **Dashboard:** `degraded:false`, read-model live, Android contract intact. ✅
- **Edge:** recent PF **0.771**, 24h PF **0.173**, lifetime PF 0.289; **100% TIMEOUT exits** (TP~54bps vs realized ~13-16bps). **NOT profitable.** Strongest segment: `BEAR_TREND` (+0.055); worst: `BULL_TREND` (−0.754). **No strategy change permitted without evidence-first mandate.**

---

## Round 1 (2026-07-16) — historical, retained for provenance

> **Purpose:** hand-off for the next round of the external audit. For every finding: what changed, where, how it was verified, the runtime result, and what still needs re-auditing. Pairs with `EXTERNAL_AUDIT_PROMPT.md`.
> **As of:** 2026-07-16 ~17:15 UTC. **Deployed SHA on server:** `c6565c3` (P0 fixes `8750a49` + clamp nit `c6565c3`; `cryptomaster.service` active since 16:42 UTC).
> **Standing constraints (unchanged):** paper-only (`TRADING_MODE=paper_live`), REAL trading = NO-GO, never enable live, every trading-core change goes through evidence → independent reviewer → reversible deploy.

> **Re-audit follow-up (external, 2026-07-16, `CryptoMaster_aktualizovane_overeni_auditu`):** static verification confirmed P0.1/P0.2/P0.3 fixed, P0.4 partial. It found ONE nit — the fail-closed clamp set `TRADING_MODE=paper` (invalid; coerced to `paper_live`, never a live bypass). **FIXED in `c6565c3`** (clamp now sets `paper_live`; tests updated). 16 P0 tests pass.
>
> **Runtime confirmation status (P0.2/P0.3): STILL PENDING — honest.** At snapshot `cryptomaster-health-517` (17:12 UTC) the bot had had **zero eligible closes since the 16:42 deploy** (newest cache row 16:20, pre-deploy; `buy_only` has low trade frequency — needs a down-deviation to fade + 15-min hold). `close_path_forensics.txt` therefore had no post-deploy `[PAPER_CANONICAL_LEARNING_UPDATE]` / quarantine markers to inspect. **The single-step `lifetime_n` and TIMEOUT_NO_PRICE-quarantine invariants are code-verified + unit-tested but NOT yet observed live.** Re-run `hetzner-fetch-health.yml` after ≥ a few post-16:42 closes and confirm from `close_path_forensics.txt`. Until then, treat P0.2/P0.3 as static-pass / runtime-pending.

---

## How to reproduce / continue

1. Read the diffs: `git log --oneline` on `main`; the P0 fix is squash-commit **`8750a49`** (PR #57).
2. Pull a fresh runtime snapshot: run `hetzner-fetch-health.yml` (`workflow_dispatch`) → download artifact `cryptomaster-health-<N>` → inspect `close_path_forensics.txt`, `edge_analysis.txt`, `cache_sqlite_probe.txt`, `service_status.txt`, `quota_forensics.txt`, `dashboard_metrics.json`.
3. Tests: `python3 -m pytest tests/test_audit_p0_correctness.py -q` (16 P0 tests) + the regression subset.

---

## P0 — resolved this round (verify at runtime)

### P0.1 — `.env` could override systemd safety env — ✅ FIXED (`8750a49`)
- **Change:** `src/services/paper_trade_executor.py:18` `load_dotenv(override=True)` → `override=False`; manual fallback loader now skips keys already in `os.environ`; new `_enforce_paper_safe_mode()` (`~:36-71`) runs at import and fail-closed **clamps** `TRADING_MODE`/`ENABLE_REAL_ORDERS`/`LIVE_TRADING_CONFIRMED` to paper-safe if a `.env` value indicates live (logs `CRITICAL [PAPER_SAFETY_OVERRIDE]`), without raising.
- **Verified:** unit tests `test_p0_1_*` (override=False present, truthy helper, live-flag clamp, paper env untouched); no other `load_dotenv(override=True)` in tree.
- **RE-AUDIT:** confirm on the server that `.env` contains no live flags and that a hostile `.env` value is actually clamped at runtime (grep journal for `[PAPER_SAFETY_OVERRIDE]`). The auditor's original concern (precedence) is structurally closed but should be runtime-confirmed.

### P0.2 — one close learned twice — ✅ FIXED (`8750a49`)
- **Change:** `bot2/main.py:~1547` now binds `_learning_instance = get_learner()` (was a distinct `PaperAdaptiveLearning()`); `set_learning_instance` always resolves to the `get_learner()` singleton; the redundant second recorder `_learning_instance.record_close(...)` at the end of `close_paper_position` was removed → `_record_adaptive_learning_close()` (eligibility-gated) is the single recorder. Added a bounded (maxlen 5000) **persistent `trade_id` dedupe ledger** in `PaperAdaptiveLearning.record_close`.
- **Reviewer-caught regression, also fixed:** the singleton rebind activated a dormant path — `check_and_close_timeout_positions` (`paper_trade_executor.py:~1995`) recorded `TIMEOUT_NO_PRICE` FLAT non-trades directly. Now guarded at **both** layers: the call site (`:1995`) and `record_close` itself (`paper_adaptive_learning.py:~458`, quarantine guard **before** dedupe/ledger write) → `[LEARNING_RECORD_CLOSE_QUARANTINE]`/`[LEARNING_RECORD_CLOSE_SKIP]`.
- **Verified:** `test_p0_2_*` (single close → `lifetime_n==1`; repeated `trade_id` deduped; dedupe survives restart; empty `trade_id` always records; `set_learning_instance` binds to singleton) + 3 regression tests (TIMEOUT_NO_PRICE / learning_skipped → `lifetime_n==0`; normal WIN still records once). Independent reviewer APPROVED.
- **RE-AUDIT (non-blocking, runtime only):** capture a post-deploy snapshot after ≥ a few closes and confirm from `close_path_forensics.txt` that `[PAPER_CANONICAL_LEARNING_UPDATE]` fires **once per close** with **monotonic single-step `lifetime_n`**, and that TIMEOUT_NO_PRICE closes emit the quarantine/skip markers rather than incrementing the counter. *(At snapshot 16:43 the bot had just restarted 1 min prior — no post-deploy closes yet; verify in the next snapshot.)* Also quantify TIMEOUT_NO_PRICE frequency to confirm the exclusion mattered.

### P0.3 — segment metrics silently dead (6-tuple vs 4-tuple) — ✅ FIXED (`8750a49`)
- **Change:** `src/services/paper_adaptive_learning.py:~1255-1290` `get_segment_metrics()` now uses length-tolerant index parsing (`e[1]==outcome`, `e[0]==pnl`, `len(e) >= 2` guard) instead of `for _, outcome, _, _ in matching`. Audited the file — this was the only fixed-arity unpack site of rolling entries.
- **Verified:** `test_p0_3_*` (non-None, correct WIN counts/PF/expectancy for 6-tuples; also legacy 4/5-tuples).
- **RE-AUDIT:** confirm at runtime that segment cooldowns for losing symbol/regime/side combos now actually activate (grep for the segment-cooldown / segment-loss log markers). Previously they never fired.

### P0.4 — dead/ambiguous local close sink — ✅ PARTIAL (`8750a49`)
- **Change:** removed the permanently-dead `from ... import on_paper_trade_closed` and its `if on_paper_trade_closed:` branch (import always failed — `learning_integration` has no such symbol). Documented `local_persistent_cache.save_closed_trade` (called from `trade_executor.py:1662`, `INSERT OR REPLACE` dedupe) as the authoritative cache.sqlite sink.
- **Verified:** `test_p0_4_*` (dead symbol absent, authoritative sink callable).
- **RE-AUDIT / OPEN:** the auditor's full recommendation — a single explicit `persist_closed_paper_trade()` atomically handling SQLite + adaptive learning + bucket metrics + outbox + dashboard cache with one `trade_id` dedupe — is **NOT** yet implemented (deferred as too risky mid-experiment). Left as a documented TODO. **This remains an open architectural item for the next round.**

---

## P1 / P2 — acknowledged, NOT yet fixed (open work for next round)

| # | Finding | Status | Note |
|---|---------|--------|------|
| P1.5 | `deploy.yml` restarts the old **V5 service** (`cryptomaster-v5-paper`) + uses `git pull` not deterministic reset | **OPEN** | Prior internal work added a paths filter but did NOT remove the V5 service ops or make deploy `git reset --hard $SHA` + `git clean -fd`. Verify whether `cryptomaster-v5-paper` still exists/ runs on the server (risk: two trading loops). |
| P1.6 | Dashboard runs as **root**, binds `0.0.0.0:5001`, no auth, shells out to `journalctl` | **OPEN** | High-severity security. Needs: dedicated non-root user, bind `127.0.0.1`, auth/reverse-proxy or VPN, systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `ProtectHome`), read-only DB access. Confirm Hetzner firewall on 5001. |
| P1.7 | `/api/dashboard/metrics/enhanced` reads dead `learning_database.sqlite` `trades` table; PF math returns ~1.0 | **OPEN** | The main `/api/dashboard/metrics` headline was fixed to a cache-sourced rolling window (PR #49), but `/enhanced` still reads the dead DB. Point all endpoints at one read model. |
| P1.8 | "WIN" definition inconsistent (learning: net > +0.05% = WIN, FLAT band; dashboard: `net_pnl_usd > 0`) | **OPEN** | Introduce a canonical `outcome = WIN|LOSS|FLAT` and compute WR everywhere by the same rule; decide FLAT handling in the denominator. |
| P2.9 | Monitoring re-interprets PnL units (double-subtracts cost verbally; %-vs-fraction factor-100 risk) | **OPEN** | Rename fields explicitly (`net_pnl_fraction`/`_pct`/`_bps`/`_usd`); ban ambiguous `pnl_pct`. |
| P2.10 | Per-tick `logging.debug` in `market_stream._dispatch()` could re-flood WS at global DEBUG | **OPEN** | Gate/remove the per-tick debug; TP_SL_EVAL and P0.5 floods are already env-gated OFF. |

---

## Trading-edge / experiment status (context, not a fix)

- **`PAPER_FADE_SIDES=buy_only`** live since 2026-07-16 08:43 UTC (reviewer-approved reversible experiment, PR #53/#54). Evidence: BUY-fades ~72% WR / +0.17 vs SELL-fades ~55% / −0.23. At 16:43: SELL frozen at 64 (filter working), BUY 71 (was 63). **Rollback triggers:** BUY-fade WR < 58%, or rolling-100 PF fails to exceed ~1.10, or regime turns bearish → `hetzner-set-fade-sides.yml fade_sides=both`.
- **Thin edge (unresolved by design):** captured DEV_FADE reversion ~20 bps ≈ simulated round-trip cost ~18 bps (`PAPER_FEE_PCT` 15 + `PAPER_SLIPPAGE_PCT` 3). PF hovers ~1.0. **Do NOT lower simulated costs to inflate results.** A genuinely stronger entry edge (not parameter tinkering) is the real lever — out of scope of the P0 fixes.
- **`PAPER_SYMBOL_BLACKLIST=BNBUSDT,XRPUSDT`** applied (0/72, 1/65 wins historically); DOTUSDT held out.
- **⚠️ Metric-trust caveat (per auditor):** until P0.2/P0.3 runtime effects are confirmed AND the P1 dashboard-consistency items are closed, **no current metric should be used to decide REAL readiness.** The `buy_only` result is a paper forward-test only.

---

## Latent items previously flagged (still open)

- Learning coverage gap: `normal_rde_take` / `paper_adaptive_recovery` closes are still **not** canonical-learned by the widened gate (only `training_sampler` / `paper_evidence_collection`). Revisit before any segment graduates to strict EV.
- `SIGNAL_INVERT_TEST=1` + `PAPER_FADE_SIDES=buy_only` double-flip footgun — the `hetzner-set-fade-sides.yml` deploy workflow refuses that combination, but the code-level interaction remains; document as an operational prohibition.

---

## Required order for the next round (auditor's list, updated)

1. ~~`load_dotenv` precedence~~ ✅ (verify at runtime)
2. ~~single learning singleton + `trade_id` dedupe~~ ✅ (+ TIMEOUT_NO_PRICE quarantine; verify `lifetime_n` single-step at runtime)
3. ~~segment 6-tuple parse~~ ✅ (verify cooldowns fire at runtime)
4. **Canonical `persist_closed_paper_trade()` handler** — still OPEN (P0.4 remainder)
5. **Remove V5 service from deploy + deterministic `git reset --hard $SHA`** — OPEN (P1.5)
6. **Unify WIN/LOSS/FLAT + PnL units** — OPEN (P1.8, P2.9)
7. **Point all dashboard endpoints at one authoritative source** — OPEN (P1.7)
8. **Secure the dashboard / drop root** — OPEN (P1.6)
9. **New read-only runtime audit** — pending items 4-8 + the runtime confirmations noted above.

---

## Final decision (unchanged)
REAL orders MUST NOT be enabled. `buy_only` may keep running in PAPER only, and its metrics must not feed any REAL-readiness decision until the double-learning, segment-metric, and dashboard-consistency items are all runtime-confirmed closed.
