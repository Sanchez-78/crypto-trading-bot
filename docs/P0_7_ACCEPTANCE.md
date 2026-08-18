# P0.7 Acceptance Report — Cost and Execution Observability

**Status:** IMPLEMENTED, UNIT_TESTED. Fail-closed startup assertion RUNTIME_VERIFIED (present in every deploy since 2026-08-07). Cost model itself not yet RUNTIME_VERIFIED against live data in isolation — first exercised in aggregate via P0.8's live wiring (`_workspace/33`, 2026-08-17).

**Commit:** `c3083ab` (2026-08-07)

## Scope

Gate G0 repository reconnaissance + Phase P0.7 per
`docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md`.

Gate G0 finding: three parallel architectures exist in the repository —
legacy (the live path), clean_core (an isolated, test-enforced research
sandbox), and v5_bot (an isolated standalone runtime).
`src/services/v5_legacy_bridge/` already provides a live, wired
evidence/outbox/quota tier — reused, not rebuilt. `shadow_excursion_recorder.py`
and `maker_fill_model_v2` already existed — audited, not duplicated.

## Files changed

| File | Purpose | Risk |
|---|---|---|
| `src/core/runtime_mode.py` | New `assert_real_orders_prohibited()` — the document's Sec 2.1 fail-closed startup assertion; five guards-at-use existed but none was a single fail-fast check | Low — additive, fail-closed only |
| `bot2/main.py` | Wired the assertion into boot, deliberately outside the existing try/except that only logs a warning, so a real-order misconfiguration halts boot instead of continuing | Low — startup-only |
| `src/services/cost_model.py` (new) | Cost model: fees, spread, slippage proxy, latency buffer, funding treatment, uncertainty buffer, net edge | Low — new module, no existing caller yet at this commit |
| `audit/entry_paths.json` (new) | §36D machine-readable entry-path inventory | None — documentation artifact |
| `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` (new) | §27.1 repository architecture report | None — documentation |

## Behavior before

No single fail-fast startup assertion existed for the real-orders
prohibition (five separate guards-at-use, no unified boot-time check). No
central cost model existed for the new strategy pipeline (the legacy
signal path has its own, separate cost-floor logic in
`paper_trade_executor.py`).

## Behavior after

Boot halts immediately if a real-order misconfiguration is detected,
instead of only logging a warning and continuing. `cost_model.py` exists
as a new, independently testable module ready for `signal_router.py`
(the next commit, `d4d69ee`) to consume.

## Tests

`tests/test_cost_model.py` (338 lines, new), `tests/test_runtime_mode_startup_assertion.py`
(130 lines, new). Exact pass counts for this specific commit not
separately recorded at the time (full-suite baseline tracking started at
the next commit, `85ef6b2`) — both files still pass as of 2026-08-18
(confirmed via the session's repeated full-suite sweeps that include
`test_paper_mode.py`/`test_deploy_integrity.py`-adjacent runs; this
specific file was not independently re-run in isolation this session,
noted as a gap).

## Known limitations

- MFE/MAE (Sec 9.8): found already substantially satisfied by existing
  `cache.sqlite` `closed_trades` columns (`mfe_gross_bps`/`mae_gross_bps`/
  `time_to_mfe_ms`/`time_to_mae_ms`, confirmed live and populated since
  2026-08-01) — no new module built this phase, by design.
- Gaps found and explicitly carried forward, not fixed this phase (scope
  discipline, not oversight): E3/E5 entry-path bypass-safety needed
  fresh assertion-level tests (addressed P0.8-adjacent); no central
  config-validation-at-startup module (document §20 requirement — still
  open as of 2026-08-18, see the document-implementation gap analysis
  in `_workspace/37_document_compliance_gap_analysis.md`); `maker_fill_model_v2`
  not wired into live paper fills; an untracked systemd config drop-in
  was found on the server at this time (a separate, pre-existing
  incident, since resolved — the overlay is now tracked, see
  `systemd/99-cryptomaster-managed-runtime.conf`'s own header history).

## Rollback

`git revert c3083ab` (or `git reset --hard` to the parent commit if not
yet pushed/deployed). No schema migration, no systemd change, no
Firestore document format change in this commit — a plain code revert is
sufficient. `cost_model.py` had zero callers at this commit, so reverting
it has zero live-behavior effect either way.

## Acceptance decision

ACCEPTED for the "must implement now" scope (§31) — additive,
zero live-behavior change at merge time (the cost model had no caller
yet), fail-closed assertion is a net safety improvement. Not yet
independently RUNTIME_VERIFIED in isolation (only as part of the P0.8+
pipeline's aggregate later verification).
