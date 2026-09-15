# External Audit — WR>50 Single-Path Refactor — Kompletní balíček

**Sestaveno:** 2026-09-15, na žádost uživatele ("kde komplexni md pro externi audit?").

**Účel:** Sloučit VŠECHNY podklady k této práci (prompt k auditu, plný 3kolový
report, architektonický mandát, retrahovaná WR analýza, původní implementační
zadání, release gate skript a jeho aktuální výstup) do jednoho souboru pro
snadné předání externímu recenzentovi. Nic zde není nové — jde o konsolidaci
existujících dokumentů (většina na větvi `wr50/canonical-single-path-phase2`,
prompt na `main`).

**Stav větve:** `wr50/canonical-single-path-phase2`, pushnuto na origin, 11
commitů, **NEmergnuto do `main`, nenasazeno**. `REAL trading = ABSOLUTE NO-GO`
nezávisle na čemkoli níže.

---

## Obsah
0. [Rychlý souhrn](#0-rychlý-souhrn)
1. [EXTERNAL_AUDIT_WR50_SINGLE_PATH_PROMPT_2026-09-14.md — prompt k auditu](#1-external_audit_wr50_single_path_prompt_2026-09-14md)
2. [CLAUDE_WR50_SINGLE_PATH_PHASE2_REPORT_2026-09-14.md — plný 3kolový report](#2-claude_wr50_single_path_phase2_report_2026-09-14md)
3. [CLAUDE_SINGLE_PATH_POLICY_2026-09-14.md — architektonický mandát](#3-claude_single_path_policy_2026-09-14md)
4. [WR_TARGET_ANALYSIS_2026-09-14.md — retrahovaná analýza (nedůvěryhodná)](#4-wr_target_analysis_2026-09-14md)
5. [CLAUDE_WR50_SINGLE_PATH_IMPLEMENTATION_PROMPT_2026-09-14.md — původní zadání](#5-claude_wr50_single_path_implementation_prompt_2026-09-14md)
6. [tools/release_gate.py — zdrojový kód + aktuální výstup](#6-toolsrelease_gatepy)
7. [Release artefakty vytvořené 2026-09-15](#7-release-artefakty)

---

## 0. Rychlý souhrn

```text
Engineering:        PARTIAL (Fáze 0-3, 5, 6 částečně; Fáze 4, 7 neuzavřeny)
Cíl WR > 50 %:       NOT_ACHIEVED (a nemohl být v tomto běhu — chybí post-fix kohort)
Release gate:        ready=true, reasons=[] — NEZÁVISLE ověřeno v izolovaném
                      git worktree (2026-09-15, po opravě gate skriptu a jeho
                      prvním vůbec commitnutí — viz Sekce 0.2 níže)
Merge do main:        NEPROVEDENO (gate splněn, ale merge/deploy je samostatné
                      rozhodnutí — viz doporučení v Sekci 0.2)
Nasazení:             NEPROVEDENO
REAL trading:         ABSOLUTE NO-GO
```

**Update 2026-09-15 (druhé kolo, po reconciliační relaci):** nezávislá
reconciliační relace (`CLAUDE_EXTERNAL_AUDIT_PACKAGE_RECONCILIATION_
2026-09-15.md`) našla zásadní věc: **`tools/release_gate.py` nebyl nikdy
commitnutý na žádné větvi** — existoval jen jako netrackovaný soubor ve
sdíleném pracovním adresáři. Fresh clone by neměl gate vůbec. Ta relace
skript zároveň opravila (`len(reasons) == 0` místo natvrdo `False`) —
nezávisle, disinterested, přesně to rozhodnutí, které předchozí kolo této
práce záměrně nechalo na někom jiném. Skript byl nyní commitnut na `main`
i na `wr50/canonical-single-path-phase2` (přes izolovaný git worktree, aby
se nesáhlo na rozdělanou práci jiné souběžné relace v `main`'s working
tree). **Gate ověřen `ready:true` v čistém worktree** (ne ve sdíleném
adresáři se všemi cizími necommitnutými soubory) — je to teď skutečný,
reprodukovatelný výsledek, ne artefakt lokálního nepořádku.

**Klíčová zjištění:**
1. Předchozí tvrzení "rde_take 75 % vs training_sampler 30 %" bylo z
   kontaminovaného 34minutového, 40 dní starého vzorku — **retrahováno**.
2. Skutečný nález: 22,5 % všech obchodů (`TIMEOUT_NO_PRICE`) dashboard počítal
   jako prohry, ačkoli obchodní kód je sám považoval za ne-obchody — **opraveno**
   jako nový stav `TradeOutcome.VOID`, ne jako filtr.
3. Testy zapisovaly do produkčních dat (jeden sink se ukázal být **připojený
   síťový disk**) — **opraveno**, se dvěma sebe-odhalenými incidenty (jeden
   řádek v produkční DB, jedno smazání `paper_open_positions.json`, oba
   opraveny a hash-ověřeny).
4. V pracovním stromu ležela hotová oprava veřejné expozice dashboardu — **NE-
   commitnuta**, protože identická oprava už jednou rozbila Android appku.
5. Release gate skript má `return False` natvrdo — **NEOPRAVENO**, čeká na
   rozhodnutí (bug vs. záměr).

---

## 1. EXTERNAL_AUDIT_WR50_SINGLE_PATH_PROMPT_2026-09-14.md

*(prompt k auditu — plné aktuální znění)*

# External audit prompt — WR>50 single-path refactor (Phase 0-3/5/6, 3 rounds)

### 0. Role and terminal boundary

You are the independent external auditor of the CryptoMaster HF-Quant paper-trading
project, continuing the same adversarial-review lineage that ruled NO-GO on
delta-neutral funding-carry (Kolo 9) and separately audited the host/code security
posture (`EXTERNAL_AUDIT_CODE_SSH_REPORT_2026-09-02.md`). This round covers a
different track: an architecture-consolidation + measurement-integrity refactor
aimed at honestly earning `WR > 50%` (paper-only), not a new trading strategy.

The work under audit lives on branch `wr50/canonical-single-path-phase2`
(pushed to origin, 11 commits, latest includes this package), never merged to
`main`, never deployed. `REAL trading = ABSOLUTE NO-GO` regardless of any verdict
below. Nothing here authorizes deployment, a restart, or a REAL order.

#### 0.1 Update (2026-09-15) — gate work since the 3 rounds above, and two new findings

Following the 3 rounds documented in the full report, the orchestrating session
(not a dispatched agent — the spend limit blocking background agents recurred)
worked the release gate directly:

- **`protected_paths_dirty` resolved.** Of the 5 protected paths, 4 were already
  clean on this branch; only `systemd/cryptomaster-dashboard.service` was dirty.
- **New finding: an uncommitted dashboard-hardening draft was sitting in that
  file** (`DASHBOARD_SECURITY_ENABLED=1`, bind `127.0.0.1`, `DynamicUser`,
  bearer-token auth via `LoadCredential`, extensive systemd sandboxing) —
  directly addressing the P0/P1 exposure `EXTERNAL_AUDIT_CODE_SSH_REPORT_
  2026-09-02.md` flagged (dashboard on `0.0.0.0:5001`, unauthenticated, root).
  **Deliberately NOT committed as part of this gate resolution**: `git log`
  shows this exact class of change was already tried once (commit `c664f3d`,
  "audit(PR5/P1.6): dashboard auth + localhost bind + non-root hardening") and
  later reverted (commit `fbcd709`, "stop recurring Android API outage") — i.e.
  binding the dashboard to loopback previously broke live Android app
  connectivity. The draft was reverted to HEAD to unblock this gate cleanly and
  preserved verbatim at `_workspace/52_uncommitted_dashboard_hardening_
  preserved_20260915.service.txt` for its own separately-scoped decision.
  **Audit this call**: was reverting-and-deferring the right choice, or should
  the hardening have shipped alongside a check for whether the Android app's
  connectivity story has changed since the `fbcd709` incident?
- **Both remaining artifacts attached**: `release_artifacts/wr50_phase2_
  manifest_2026-09-15.json` (SHA-256 manifest, commit identity, explicit
  scope/exclusions) and `release_artifacts/wr50_phase2_paper_smoke_evidence_
  2026-09-15.txt` (fresh 61-test run + reference to the already-verified
  207-test/6-mutant evidence from the full report).
- **New finding: `tools/release_gate.py` appears to have a bug.** Its
  `evaluate()` function's final line is `return False, reasons, hashes` — the
  `ready` flag is a **hardcoded `False` literal**, not `len(reasons) == 0`.
  After resolving all three original blockers, `python tools/release_gate.py
  --json --artifact ... --paper-smoke-evidence ...` now returns `"reasons": []`
  (empty — every condition the script itself checks is satisfied) but
  `"ready": false` and exit code `2` regardless. **This was deliberately NOT
  patched by the same session trying to pass the gate** — fixing the checker
  that grades your own readiness is exactly the self-certification this
  project's adversarial-review culture exists to prevent. **Rule on this
  specifically**: is `return False, ...` a genuine bug (should be `len(reasons)
  == 0`), or an intentional design forcing every deploy through a manual
  override regardless of automated checks? Either answer has a different
  correct next action, and neither should come from the session with an
  interest in the outcome.

Updated terminal state: engineering `PARTIAL` (unchanged), release gate
`reasons=[]` but `ready=false` (script anomaly, see above), nothing merged or
pushed to `main`, nothing deployed, zero REAL orders throughout.

Full evidence: Section 2 below (3 rounds, 686 lines — read it in full, don't
work from this prompt's summary alone). Governing architecture mandate:
Section 3. Original task spec: Section 5. Prior WR-by-source claim that this
work **retracted**: Section 4 (its 75%/30% figures came from a 34-minute,
39.8-day-old, 24.6%-synthetic-contaminated slice — do not treat as valid
evidence, and check whether the retraction itself was done correctly).

### 1. What happened, in one table (verify this yourself against the report, don't take it as given)

| Round | Claimed done | Claimed NOT done |
|---|---|---|
| 1 | Phase 0 baseline+contamination audit; Phase 1 RED tests (2 suites); Phase 2 core (9 call-sites → one `canonical_admit()` wrapper); Phase 5 partial (dashboard qualified/excluded fields); Phase 6 partial (3 mutants) | Phase 2 attribution *persistence* (no schema columns existed); Phase 3, 4, 7 |
| 2 | Test-sink separation for `cache.sqlite` (root cause: relative path resolved against CWD); schema migration (6 columns) + fixed a second gap (position-dict allowlist silently dropping 4/6 stamped fields); Phase 3 (`TIMEOUT_NO_PRICE` → new `TradeOutcome.VOID` state, not a filter); 2 more mutants (M4/M5) | Sink separation for the other 2 production files; test-order-dependence fix; Phase 4 |
| 3 | Sink separation extended to `learning_database.sqlite` (discovered: resolves to a **mounted network share**, not just CWD-relative) and `paper_open_positions.json`/`paper_adaptive_learning_state.json`; centralized guard (`src/core/test_sink_guard.py`); test-order-dependence fixed (autouse fixture pins `_PAPER_STATE_STATUS=READY`) with a measured (git-worktree-isolated) before/after: 30failed/45passed → 24failed/51passed; 1 more mutant (M6) | 24 pre-existing failures in `test_p1_paper_exploration.py`; a full sweep for other hardcoded production paths (only one pattern was audited); Phase 4 itself |

**Two disclosed near-miss incidents**, both self-caught (not caught by any external
check), both reverted with SHA-256 verification:
1. Round 2: the agent's own RED-state-confirmation probe wrote one row
   (`id=58840`, `trade_id=paper_sinkprobe01`) into the live production
   `cache.sqlite` — reproducing the exact bug being fixed, on itself.
2. Round 3: 39 hardcoded literal paths in `test_p1_paper_exploration.py` bypassed
   the module-constant redirect entirely and **deleted** the real
   `data/paper_open_positions.json` during a full-suite run. Gitignored, so it
   never showed in `git status` — caught only because the agent was independently
   hashing production files before/after every run.

### 2. Adversarial checks I want you to actually run, not just read about

1. **Re-derive the contamination math yourself.** 116/472 = 24.6%; 76 fake-clock +
   35 TEST/MANUAL (all wins) + 3 SYM* symbols. Does the union arithmetic hold? Does
   "all 35 TEST/MANUAL rows are wins" actually bias WR upward by the claimed
   direction and magnitude, or is this asserted without a counterfactual
   (WR with vs. without those 35 rows, holding everything else fixed)?
2. **Check `canonical_admit()` is genuinely a passthrough, not a second brain.**
   The report claims it "contains no admission logic... cannot re-decide, bypass,
   or retry admission." Read the actual wrapper in
   `src/services/paper_trade_executor.py` and confirm this against the 9 call-sites
   it now serves — does any call-site's pre-existing surrounding logic still make
   an admission-relevant decision *before* calling the wrapper, in a way that could
   look like "single path" on paper but isn't in practice?
3. **Stress the VOID-outcome fix.** Verify `compute_win_rate` truly excludes VOID
   only, not also silently excluding something else (the report's own M4 mutant
   claims to have tested exactly this — check the mutant's diff is what it claims,
   and that no OTHER path recomputes WR without going through the audited
   function). Does the dashboard's `_qualified_window_metrics` reconcile
   (`raw_n == qualified_n + excluded_n`) against a case with BOTH a VOID row and a
   legacy pre-fix TIMEOUT_NO_PRICE row in the same window (mixed old/new
   semantics) — the report only shows single-window reconciliation, not a mixed
   case.
4. **Verify the "not a metric trick" claim independently.** `qualified_win_rate_pct
   = 64%` is repeatedly, loudly flagged as NOT goal-met. Confirm: does the
   `test_all_source_headline_is_not_redefined` test actually assert the headline
   field's value/name is unchanged, or only that a *differently-named* field
   exists? A determined future editor could still quietly swap which field the
   Android app or a future dashboard reads — is there a structural guard against
   that class of drift, or only a test that would need to be remembered and kept
   passing?
5. **Audit the sink-separation guard for the exact failure mode it was built to
   prevent.** `_assert_not_production_sink()` triggers on `PYTEST_CURRENT_TEST`
   being set. Is there any code path (a subprocess spawned by a test without
   inheriting that env var, a test that imports and calls production code via
   `multiprocessing`, a fixture that clears `os.environ`) that could evade this
   check while still being "run under pytest" in every way a developer would
   recognize? The report itself flags "other tests may hold more hardcoded
   production paths... not yet swept" — is the guard's env-var-based detection
   robust even against paths the sweep hasn't found yet, or does it only catch
   the *redirected-constant* violation pattern, not a genuinely hardcoded
   absolute path that never goes through the constant at all?
6. **Check the worktree-based before/after measurement (R3-F) for a subtle bias.**
   Baseline was run at `f01b19f` (mid-branch, after some of this session's own
   fixes were already committed) with `FORCE_LOCAL_STORAGE`, not at the branch's
   pre-existing base commit on `main`. Does comparing branch-commit-N against
   branch-commit-M (both already containing several of this session's changes)
   correctly isolate "caused by the order-dependence fix" from "caused by
   something else fixed between those two commits"? Would comparing against the
   actual `main` HEAD give a materially different (larger or smaller) delta?
7. **Ownership/mixed-commit risk.** Four production files are explicitly flagged
   as carrying "mixed" ownership with unrelated prior sessions' uncommitted work
   (STATE-02 loader, READY guard, ROUTE-01, dashboard fields) baked into the same
   commits. If that prior work is later abandoned, reverted, or conflicts with a
   fix from a different session, what breaks in `canonical_admit()`'s dependency
   on it? Name the single most load-bearing piece of that "mixed" prior work this
   refactor now depends on, and whether that dependency is tested independently
   of this branch's own tests.
8. **Merge-readiness, independent of Phase 4.** The release gate is about
   *deployment*, not about whether this branch is safe to merge into `main` as
   an internal refactor with no behavior change to admission decisions. Should
   merge-to-main and deploy-to-production be treated as two separate gates
   here? If yes, what would the (much lighter) merge-only gate need that isn't
   already satisfied?

### 3. Specific questions to rule on

**Q1 (architecture).** Does Phase 2's `canonical_admit()` genuinely satisfy the
Single Path Policy's contract (`signal -> canonical admission -> open ->
one close writer -> metrics`, sources as labels only), or does it satisfy the
*letter* of "one wrapper" while multiple pre-wrapper decision points still exist
across the 9 call-sites? Cite specific file:line evidence either way.

**Q2 (measurement integrity).** Is the VOID-outcome fix + qualified/raw dashboard
split methodologically sound, or does it introduce a new risk (e.g., future
confusion between VOID and FLAT, or a path where VOID rows silently affect P&L
sums despite being excluded from the WR denominator)?

**Q3 (process risk from the two near-misses).** Two accidental production writes
happened in one session, both self-caught only through the operator's own
discipline (hashing files around each run), not through any structural
guarantee that existed *before* this session started. Is "hash files before/after
and disclose if they change" an adequate standing practice for this project going
forward, or does this warrant a permanent, automated pre/post-test integrity
check (e.g., a pytest session-scoped fixture that hashes the three production
files and fails the whole run if they differ) rather than relying on an operator
remembering to do this by hand each time?

**Q4 (prioritization).** Given: (a) Phase 4 is blocked on wall-clock data
accumulation and cannot be accelerated, (b) 24 pre-existing test failures exist
in `test_p1_paper_exploration.py`, (c) a hardcoded-path sweep hasn't been done
beyond the one pattern found, (d) separately, `EXTERNAL_AUDIT_CODE_SSH_REPORT_
2026-09-02.md`'s still-open findings (dashboard on `0.0.0.0:5001` without auth,
disk ~96% full, host/local SHA drift) remain unaddressed and are a live
production exposure independent of this refactor — rank these for the operator.
Should any of (b)/(c) happen before or in parallel with waiting on Phase 4's data
accumulation? Should (d) take priority over all of the WR50 work, given it's a
standing security/capacity risk on a live host regardless of trading outcome?

**Q5 (Phase 4 design review, prospective).** The next session will need to design
a real Phase 4 shadow cohort: fixed `code_version`/`config_version`, minimum
sample size, confidence interval, max-loss cap, holdout window, `training_sampler`
vs `rde_take` comparison without dropping rows. Propose the specific minimum
sample size and confidence-interval methodology you'd require before accepting a
future "WR>50 achieved" claim on this cohort, given the clean (contamination-free)
historical split was `rde_take` 99/118=83.90% vs `training_sampler` 57/221=25.79%
— both on a stale, non-version-homogeneous, unpushed-fix-predating cohort that
must not be reused as if it were live.

### 4. Ground rules (unchanged from this project's standing practice)

Be adversarial; refute where the evidence allows. Cite file:line, not paraphrase,
wherever you make a factual claim about the code. Do not soften a verdict for
continuity — if something in Phase 2/3/5/6 is unsound, say so plainly, the same
way Kolo 9 said NO-GO on funding-carry despite genuinely rigorous supporting work.
REAL trading stays an absolute NO-GO regardless of any answer above.

---

## 2. CLAUDE_WR50_SINGLE_PATH_PHASE2_REPORT_2026-09-14.md

*(plný 3kolový report, 686 řádků — hlavní evidenční dokument)*

# CLAUDE — WR >50 single-path implementation, Phase 0–3/5/6 report (2026-09-14)

> **Round 2** (test-sink separace `cache.sqlite`, schema migrace, Fáze 3) a
> **Round 3** (všechny zbývající sinky, závislost na pořadí testů) jsou
> v sekcích na konci dokumentu. Terminální stav cíle se ani v jednom kole
> **nezměnil**: `NOT_ACHIEVED`.

### Terminální stav

| Rozměr | Stav |
|---|---|
| Cíl `WR > 50 %` (paper, čistý post-fix kohort) | **`NOT_ACHIEVED`** |
| Engineering (Fáze 0–3, 5, 6 částečně) | **`PARTIAL`** |
| Release gate | **`NOT_READY_FOR_DEPLOYMENT`** |
| Live host identity / runtime content | **`NOT_VERIFIED`** (v této relaci žádné SSH) |
| REAL trading | `ABSOLUTE NO-GO` — nedotčeno |

Žádný hybridní status. Cíl WR >50 **nebyl** dosažen a v tomto běhu ani nemohl
být: neexistuje čerstvý post-fix kohort (viz Fáze 0).

---

### Fáze 0 — baseline a evidence (HOTOVO, s nálezy, které mění premisu)

Read-only agregace `local_learning_storage/cache.sqlite` (`mode=ro`, 472 řádků).

#### F0-A: lokální DB je 39,8 dne stará

Nejnovější reálný close je `2026-08-05 11:06 UTC`; „teď" je `2026-09-14`.
Tento snapshot **není live kohort** a nemůže potvrdit ani vyvrátit WR >50
pro současný kód.

#### F0-B: DB obsahuje syntetickou testovací kontaminaci (116/472 = 24,6 %)

| Třída | n | Poznámka |
|---|---|---|
| `exit_ts < 2001` (fake clock, 1970-01-01) | 76 | testovací fixtures |
| `exit_reason` ∈ {`TEST`,`MANUAL`} | 35 | **všechny `win=1`** |
| `symbol` = `SYM0/SYM1/SYM2` | 3 | syntetické symboly |
| **union** | **116** | |

Testovací zápisy skončily ve stejné DB, kterou čte dashboard a všechny
dosavadní WR analýzy. `TEST`/`MANUAL` řádky jsou 100 % wins → **nadhodnocují WR**.

#### F0-C: dosavadní „recent-100" okno je 34minutový výsek

Okno `recent-100` použité v `WR_TARGET_ANALYSIS_2026-09-14.md` pokrývá
`2026-08-05 10:32 .. 11:06 UTC` = **2 058 s (34,3 min)** a samo obsahuje
6 syntetických řádků (3 `TEST` + 3 `MANUAL`, všechny wins).

**Důsledek:** dřívější závěr „rde_take 75 % vs. training_sampler 30 %,
agregovaně 48 %" je čten z 34minutového výseku 40 dní staré, kontaminované DB.
Rozdíl mezi zdroji je reálný a na čistém kohortu ještě výraznější (níže), ale
ta konkrétní čísla nejsou platný kohort.

#### F0-D: baseline s denominatorem a intervalem nejistoty

Všechny řádky (`n=472`), all-source:

| Okno | n | wins | WR | CI95 | Σ `pnl_pct` |
|---|---|---|---|---|---|
| lifetime | 472 | 230 | 48,73 % | [44,2; 53,2] | +152,59 |
| recent-100 | 100 | 48 | 48,00 % | [38,5; 57,7] | +25,50 |

Po odstranění syntetické kontaminace (**real-clock, non-test**, `n=356`):

| Segment | n | wins | WR | Σ `pnl_pct` |
|---|---|---|---|---|
| **celkem** | **356** | **157** | **44,10 %** | **+97,86** |
| `rde_take` | 118 | 99 | 83,90 % | +67,56 |
| `training_sampler` | 221 | 57 | 25,79 % | +31,48 |
| `paper_evidence_collection` | 4 | 0 | 0,00 % | −0,32 |
| `normal_rde_take` | 4 | 0 | 0,00 % | −0,32 |
| `NULL` (UNQUALIFIED) | 8 | 1 | 12,50 % | −0,36 |

Exit taxonomie na čistém kohortu:

| exit_reason | n | wins | WR | Σ `pnl_pct` |
|---|---|---|---|---|
| `TP` | 137 | 137 | 100 % | +121,14 |
| `TIMEOUT` | 136 | 20 | 14,71 % | −23,28 |
| `TIMEOUT_NO_PRICE` | 83 | 0 | 0,00 % | **+0,000** |

#### F0-E: `TIMEOUT_NO_PRICE` — dva denominatory si odporují

106 řádků (22,5 % celé DB) má **`exit_price = 0.0`, `pnl_pct = 0.0`, `win = 0`**
— bez výjimky. Jde o pozice uzavřené, aniž kdy byla získána tržní cena.

Obchodní kód je sám považuje za **ne-obchody**:
`paper_trade_executor.py` jim nastavuje `learning_skipped=True`, přeskakuje
`record_close()`, a `paper_close_pipeline.canonical_learning_eligibility()`
je odmítá s explicitním důvodem `timeout_no_price_invalid`.

Dashboard (`dashboard_web.py:_rolling_window_metrics`) ale tytéž řádky čte z
`closed_trades` a každý z nich účtuje jako **PROHRU** (`pnl_pct = 0.0` není
`> 0`). **Dva denominatory v jednom systému se neshodnou na tom, co je obchod.**

#### F0-F: chybějící Phase-2 attribution sloupce

Ve schématu `closed_trades` **zcela chybí**: `code_version`, `config_version`,
`segment_key`, `admission_route`, `admission_reason`, `effective_hold_s`.
Dále `bucket` je NULL u 204/472 a `tp_sl_profile` = `"unknown"` u 459/472.

---

### Fáze 1 — production-linked RED testy (HOTOVO pro rozsah Fáze 2)

Každý RED byl spuštěn proti **skutečnému production source**, ne proti modelu,
a selhal na očekávané business assertion (ne na import/setup chybě).

| Test | RED | GREEN |
|---|---|---|
| `tests/test_canonical_admission_contract.py` (5 nodes) | `5 failed` | `5 passed` |
| `tests/test_dashboard_denominator_reconciliation.py` (4 nodes) | `3 failed, 1 passed` | `4 passed` |

RED-1 vyjmenoval přesně 9 přímých call-siteů (shoda s ruční inventurou).
V reconciliation sadě je `test_all_source_headline_is_not_redefined`
**anti-gaming kontrola** — musí být zelená před i po změně, a je.

---

### Fáze 2 — canonical admission (JÁDRO HOTOVO, persistence PARTIAL)

#### Inventura call-siteů (Fáze 0 bod 1)

Devět produkčních call-siteů `open_paper_position()`, všechny nyní převedeny:

| Soubor:řádek | Funkce | Route |
|---|---|---|
| `realtime_decision_engine.py:3066` | `_try_discovery_admission` | `PAPER_TRAINING` |
| `realtime_decision_engine.py:4150` | `evaluate_signal` | `PAPER_TRAINING` |
| `realtime_decision_engine.py:4235` | `evaluate_signal` | `PAPER_TRAINING` |
| `trade_executor.py:1873` | `_maybe_route_to_paper_training` | `TRAINING_SAMPLER` |
| `trade_executor.py:2289` | `handle_signal` | `PAPER_EXPLORE` |
| `trade_executor.py:3007` | `handle_signal` | `RDE_TAKE` |
| `paper_exploration.py:714` | `maybe_open_paper_exploration_from_reject` | `PAPER_EXPLORE` |
| `p0_8_plus_live_pipeline.py:295` | `run_live_tick` | `P0_8_PLUS_EVIDENCE_COLLECTION` |
| `paper_trade_executor.py:4722` | `_on_signal_created` | `P0_GATE` |

#### Zavedený kontrakt

`paper_trade_executor.canonical_admit(*, signal, price, ts, route, reason, extra)`
— keyword-only, vrací výsledek choke plus normalizované `outcome` ∈
{`OPENED`, `BLOCKED`}. Wrapper **neobsahuje žádnou admission logiku**:
razítkuje attribution, deleguje verbatim na `open_paper_position()` a
normalizuje výsledek. Nemůže admission přerozhodnout, obejít ani opakovat.

- `effective_hold_s` **znovupoužívá** existující `_effective_paper_hold_s()`
  — nezavádí druhé pravidlo pro hold (požadavek „jeden `effective_hold_s`").
- Neznámá verze zůstává `"UNKNOWN"`, nikdy se nedopočítává odhadem
  (Fáze 2 pravidlo 4). `segment_key` se nefabrikuje.
- Nerozpoznaný návrat choke je fail-closed → `BLOCKED`.

#### Co v Fázi 2 HOTOVO NENÍ

Attribution se nyní **předává** do `open_paper_position()`, ale
**nepersistuje se do `closed_trades`** — sloupce ve schématu neexistují (F0-F).
Dokud nebude provedena schema migrace, Fáze 2 bod 2 zůstává `PARTIAL`.

---

### Fáze 5 — dashboard denominator (PARTIAL, nenasazeno)

Přidáno `dashboard_web._qualified_window_metrics()` a pole
`qualified_win_rate_pct`, `qualified_win_rate_denominator`,
`qualified_excluded_non_trades`, `qualified_excluded_by_reason`,
`qualified_metrics_scope`, `qualified_reconciles`.

Vylučovací pravidlo je **jediné** a zrcadlí existující kontrakt obchodního
kódu (`TIMEOUT_NO_PRICE` → `timeout_no_price_invalid`). Nesmí růst jen proto,
že nějaká třída řádků prodělává.

Invariant Fáze 4 `raw_n == qualified_n + excluded_n` platí konstrukčně a je
ověřen na reálné lokální DB:

| Okno | raw n / WR | qualified n / WR | excluded | reconciles |
|---|---|---|---|---|
| recent-100 | 100 / **48,00 %** | 75 / **64,00 %** | 25 | `100 == 75 + 25` ✓ |
| celá DB | 472 / **48,73 %** | 366 / **62,84 %** | 106 | `472 == 366 + 106` ✓ |

> **VÝSLOVNÉ VAROVÁNÍ PROTI DEZINTERPRETACI.**
> `qualified_win_rate_pct = 64 %` **NENÍ splnění cíle WR >50** a nesmí tak být
> citováno. Je to jiné (a obhajitelné) *měření týchž obchodů*, ne zlepšení
> obchodování. All-source headline zůstal **nezměněn na 48,00 %** a test
> `test_all_source_headline_is_not_redefined` to vynucuje.
> Podmínky Fáze 4 nesplněno: kohort **není** post-fix (předchází všem změnám
> této relace), **není** versionově homogenní, **není** reprodukován na
> holdout okně, a obsahuje 116 syntetických řádků a 204 NULL bucket řádků.

---

### Fáze 6 — mutation-kill (PARTIAL: 3 mutanti, ne plná matice)

Každý mutant prošel čistým baseline importem a selhal **pouze** na očekávané
assertion (žádný SyntaxError/ImportError/timeout/no-op).

| # | Mutace | Výsledek | Zabito assertion |
|---|---|---|---|
| M1 | odstraněno `stamped["admission_route"] = route` | **KILLED** | `canonical_admit did not stamp 'admission_route'` |
| M2 | `outcome` vždy `"OPENED"` | **KILLED** | `assert 'OPENED' == 'BLOCKED'` |
| M3 | **WR-gaming**: tiše vyřadit prodělečné řádky z qualified kohortu | **KILLED** (2 nezávislé assertions) | `assert 7 == 5`; `qualified_win_rate_pct != 60.0` |

M3 je nejdůležitější: dokazuje, že testy brání přesně té manipulaci, kterou
zadání zakazuje. Po každém mutantu byl strom vrácen; `git diff HEAD` pro oba
dotčené soubory je **prázdný**.

---

### Testy — přesné příkazy a výsledky

```text
python -m pytest tests/test_canonical_admission_contract.py \
  tests/test_dashboard_denominator_reconciliation.py \
  tests/test_dashboard_metrics_contract.py tests/test_dashboard_contract_fixes.py \
  tests/test_route_open_result_contract.py tests/test_trade_executor_open_result_contract.py \
  tests/test_state_02_loader_production_red.py tests/test_state_02_save_ack_contract.py \
  tests/test_state_02_subscription_boundary_red.py tests/test_state_02_subscription_runtime.py \
  tests/test_audit_p0_correctness.py tests/test_hotfix_paper_state_wrapper.py \
  tests/test_f8b_integration.py tests/test_live_quote_cache_v1_bypass.py \
  tests/test_order_flow_features_bypass.py tests/test_dynamic_trend_exit_v1_bypass.py \
  tests/test_sec_01_dashboard_boundary.py -p no:cacheprovider -q
-> 157 passed, 2 failed, 9 skipped   (exit 1)
```

#### Pre-existing selhání (NEzpůsobená touto relací)

| Test | Příčina | Důkaz, že je pre-existing |
|---|---|---|
| `test_f8b_integration.py::test_tick_hook_before_blacklist_gate_and_gated` | hledá substring v `signal_generator.py` | `signal_generator.py` není v `git status` ani touto relací měněn |
| `test_sec_01_dashboard_boundary.py::test_spa_handler_only_serves_fixed_index` | `bytes` vs `str` TypeError | netýká se metrik; soubor je necommitovaná práce dřívější relace |
| `test_observe_gate_choke.py` (5), `test_learning_hook_evidence_collection.py` (4) | `paper_state_not_ready` / `UNINITIALIZED` | `git show HEAD:...paper_trade_executor.py \| grep paper_state_not_ready` → **žádná shoda**; READY guard je necommitovaná práce dřívější relace |

#### Selhání, která tato relace ZPŮSOBILA a OPRAVILA

`test_f8b_integration.py` — 2 nodes lokalizovaly „the real open call site"
podle jména `open_paper_position(\n`; přejmenováním se posunul na
`canonical_admit(\n`. Testy aktualizovány na nové jméno, **sémantika
assertions zachována** (ordering `record < ret < open_call` beze změny).

---

### Změněné soubory a ownership caveat

Commit `2d68876` na větvi **`wr50/canonical-single-path-phase2`**
(pushnuto), 9 souborů, +923/−124.

| Soubor | Ownership |
|---|---|
| `src/services/paper_exploration.py` | **čistě tato relace** |
| `src/services/p0_8_plus_live_pipeline.py` | **čistě tato relace** |
| `tests/test_canonical_admission_contract.py` | **nový, tato relace** |
| `tests/test_dashboard_denominator_reconciliation.py` | **nový, tato relace** |
| `tests/test_f8b_integration.py` | tato relace (follow-up přejmenování) |
| `src/services/paper_trade_executor.py` | **SMÍŠENÉ** — obsahuje i necommitovanou práci dřívějších relací (STATE-02 loader / READY guard / save-ack) |
| `src/services/realtime_decision_engine.py` | **SMÍŠENÉ** — ROUTE-01 caller handling |
| `src/services/trade_executor.py` | **SMÍŠENÉ** — ROUTE-01 exploration caller |
| `src/services/dashboard_web.py` | **SMÍŠENÉ** — canonical fields, `/api/metrics` alias |

Práce dřívějších relací nebyla od této změny **oddělitelná** (týž soubor,
prolnuté hunky). Commit tuto výhradu nese ve své zprávě.
Runtime SQLite/WAL/SHM a nesouvisející auditní soubory **nebyly** stageovány,
kopírovány, hashovány ani mazány.

---

### Release gate (Fáze 7)

```text
python tools/release_gate.py --json
-> ready=false
   reasons = [protected_paths_dirty,
              immutable_artifact_not_created,
              paper_smoke_evidence_not_attached]
```

Stav **nezměněn** touto relací (v okamžiku vzniku tohoto reportu — od té doby
viz Sekce 0.1 v Sekci 1 výše, kde jsou 2 ze 3 podmínek vyřešeny a nalezen
podezřelý `return False` v samotném skriptu). SHA-256 protected paths po
změnách:

| Soubor | SHA-256 (prefix) |
|---|---|
| `src/services/paper_trade_executor.py` | `cb344b4d4bdac9e6…` |
| `src/services/dashboard_web.py` | `636b532b779abbd0…` |
| `src/services/realtime_decision_engine.py` | `94d730681529e550…` |
| `src/services/trade_executor.py` | `dec895b4be1b619f…` |
| `systemd/cryptomaster-dashboard.service` | `cbe5646796b15281…` (nezměněno) |

Gate nebyl obcházen. `NOT_READY_FOR_DEPLOYMENT` trvá (viz aktuální stav v
Sekci 1, 0.1).

---

### Počty (tato relace, Round 1)

```text
REAL orders                         = 0
external/network calls              = 0
production writes                   = 0
deployments / restarts / kills      = 0
SSH commands                        = 0   (žádná SSH inventura neproběhla)
runtime/SQLite/WAL/SHM writes       = 0   (všechna čtení mode=ro)
git push                            = 0
git reset --hard / git checkout <path> = 0
local commits                       = 1   (větev, ne main)
live identity / runtime content     = NOT_VERIFIED
```

Bezpečnostní nálezy z `EXTERNAL_AUDIT_CODE_SSH_REPORT_2026-09-02.md`
(dashboard na `0.0.0.0:5001` bez auth, disk 96 %, host/local SHA drift)
zůstávají **OPEN** a mimo rozsah této relace, dle zadání.

---

### Reziduální rizika

1. **Nejzávažnější:** `TIMEOUT_NO_PRICE` je 22,5 % všech closes. Fáze 5 ho
   zviditelnila, ale **neodstranila příčinu** — pozice se stále zavírají bez
   tržní ceny. To je defekt exit/price cesty (Fáze 3), ne metrický problém.
2. Attribution z `canonical_admit()` se nikam nepersistuje (F0-F) — dokud
   nebude schema migrace, versionově homogenní kohort Fáze 4 nelze sestavit.
3. Lokální DB je kontaminovaná testovacími zápisy; je třeba oddělit testovací
   sink od produkčního `cache.sqlite`, jinak bude každá budoucí WR analýza
   znovu zkreslená. **Nic nebylo mazáno.**
4. Commit mísí ownership se třemi dřívějšími relacemi (viz výše).
5. Devět pre-existing test failures zůstává otevřených.

---

### Přesný další krok (v době vzniku Round 1 — od té doby proveden, viz Round 2/3)

**Fáze 3 na `TIMEOUT_NO_PRICE`**, v tomto pořadí:

1. Production-linked RED test: pozice, které vyprší bez čerstvé ceny, nesmí
   být zapsány jako `win=0` s `exit_price=0.0`; buď se získá reálná cena,
   nebo se pozice karantenizuje **mimo** `closed_trades`.
2. Teprve poté schema migrace `closed_trades` o šest chybějících Phase-2
   sloupců, aby `canonical_admit()` attribution skutečně persistovala.
3. Teprve s (1) a (2) živě běžícími začít Fázi 4 shadow kohortu s předem
   zafixovaným `code_version`/`config_version`, minimální velikostí vzorku a
   holdout oknem — to je jediná cesta, jak lze WR >50 legitimně tvrdit.

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.

---
---

## Round 2 — test-sink separace, schema migrace, Fáze 3

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
Engineering: `PARTIAL` (nově uzavřena Fáze 3 a persistence Fáze 2).
Release gate: `NOT_READY_FOR_DEPLOYMENT`. Deploy/restart/SSH/REAL orders: `0`.

### R2-A — Separace testovacího sinku (příčina kontaminace z Fáze 0)

**Root cause:** `local_persistent_cache.LOCAL_DB_PATH` byl module-level
**relativní** konstanta (`local_learning_storage/cache.sqlite`) rozhodovaná
podle CWD procesu, bez jakéhokoli override. pytest běží z kořene repa, takže
každý test, který uzavřel paper pozici, zapisoval přímo do téže databáze,
kterou čte dashboard a ze které se počítá každá WR analýza.

**Oprava — dvě vrstvy:**

1. Adresář se řeší z `CRYPTOMASTER_LEARNING_STORAGE_DIR`; `tests/conftest.py`
   přesměruje celou session do dočasného adresáře už v okamžiku importu
   conftestu (dřív, než kterýkoli testový modul importuje cache modul).
2. `_assert_not_production_sink()` jako **strukturální fail-closed pojistka**:
   pod pytestem je zápis do adresáře jménem `local_learning_storage` odmítnut,
   ne tiše proveden. Volá se **mimo** `try` blok v `save_closed_trade()`, aby
   porušení shodilo příslušný test a nebylo spolknuto handlerem na cache výpadky.

Produkční běh nedotčen (`PYTEST_CURRENT_TEST` tam není nastaven).

**Důkaz účinnosti:** produkční `cache.sqlite` má **472 řádků před i po**
každém dalším testovém běhu v této relaci, včetně sad, které ji dříve
kontaminovaly.

> **DISCLOSURE — vlastní kontaminace během ověřování RED stavu.**
> Můj vlastní probe test (`RED-4`) zapsal do produkční `cache.sqlite` jeden
> řádek (`id=58840`, `trade_id=paper_sinkprobe01`) — tedy přesně ten bug, který
> opravuji, reprodukovaný nedopatřením na sobě. Řádek byl odstraněn přesným
> párováním `id` + `trade_id`, počet ověřen zpět na 472. **Žádný jiný řádek
> nebyl dotčen.** Historická kontaminace (116 řádků z Fáze 0) byla ponechána
> beze změny — nic se nemazalo ani nebackfillovalo.

### R2-B — Schema migrace + persistence attribution (uzavírá Fázi 2 bod 2)

Fáze 0 zjistila, že šest Phase-2 sloupců ve schématu **vůbec neexistuje**,
takže `canonical_admit()` razítkoval attribution, která neměla kam přistát.
Musely se zavřít **dvě** mezery, ne jedna:

1. **Schema + INSERT**: `code_version`, `config_version`, `segment_key`,
   `admission_route`, `admission_reason`, `effective_hold_s` přidány stávajícím
   aditivním idempotentním ADD-COLUMN-if-missing vzorem a zapisovány v
   `save_closed_trade()`. Chybějící hodnota zůstává `NULL` (UNQUALIFIED),
   nikdy se nedoplňuje aktuálním buildem.
2. **Hranice pozice**: position dict v `open_paper_position()` je **explicitní
   allowlist** klíčů z `extra` — čtyři z razítkovaných polí se tam tiše
   zahazovaly a nikdy nemohly dorazit ke close writeru. Totožný tvar jako
   attribution write bug z 2026-08-18. `close_paper_position()` staví closed
   trade jako `{**pos, ...}`, takže pojmenování v tom dictu je to, co je činí
   persistovatelnými.

Poznámka k `segment_key`: executor jej na P0.3C evidence reroute
**deterministicky přepočítává** na
`f"{symbol}_{side}_{regime}_{source}_{tp_sl_profile}"`.
Tento přepočet JE kanonická forma, takže end-to-end test tvrdí „jeden neprázdný
symbol-scoped segment_key", nikoli „vyhrává hodnota volajícího".

### R2-C — Fáze 3: no-price expiry je VOID, ne prohra

**Nález Fáze 0:** 106 z 472 řádků (22,5 %) má `exit_reason=TIMEOUT_NO_PRICE`
a **bez výjimky** `exit_price=0.0`, `pnl_pct=0.0`, `win=0`.

Obchodní kód je už považoval za ne-obchody (`learning_skipped=True`, žádný
`record_close`, odmítnuto jako `timeout_no_price_invalid`). Persistovaný řádek
tvrdil opak, takže **zamrzlý price feed se četl jako 106 proher**.

**Oprava je distinktní stav, nikoli post-hoc filtr:**

| Změna | Proč |
|---|---|
| `TradeOutcome.VOID` | absence měřitelného výsledku; odlišné od `FLAT` (reálný obchod uvnitř ±0,05 pp deadbandu). VOID se obchodem nikdy nestal. |
| `exit_price=None`, `win=None` | `0.0` tvrdí, že trh vytiskl nulovou cenu — to je nepravda. Neznámé se zapisuje jako neznámé. |
| `save_closed_trade` NULL-preserving | `1 if trade.get("win") else 0` byl přesně ten řádek, který z UNKNOWN udělal zaznamenanou prohru. |
| `compute_win_rate` vylučuje VOID | VOID nenese P&L ani v jednom směru. **Každý reálný obchod — každý FLAT i každá LOSS — v denominátoru zůstává.** |
| `_qualified_window_metrics` čte i `outcome=VOID` | dva ekvivalentní signály téhož faktu; legacy řádky nesou jen `exit_reason`. |

`gross/net_pnl_pct` zůstává `0.0` (nikoli `None`) — vědomé, disclosnuté
rozhodnutí: v paper účetnictví se nic nezaúčtovalo a navazující PF/net-sum
aritmetika potřebuje číslo. Řádek je z denominátorů držen přes
`outcome`/`exit_reason`, ne přes hodnotu P&L.

**Žádný backfill.** Ověřeno na reálné DB: všech 106 historických řádků má
stále `win=0` a `outcome != VOID`. Oprava působí pouze na nové closy.
Vyloučení historických řádků nadále funguje přes legacy `exit_reason` marker —
právě proto jsou v readeru ponechány oba signály.

### R2-D — Mutation-kill (Round 2)

| # | Mutace | Výsledek | Zabito assertion |
|---|---|---|---|
| M4 | **anti-gaming**: vyřadit z denominátoru i `LOSS` | **KILLED** | `assert 0.5 == 0.333…` (WR by vyskočila 33 % → 50 %) |
| M5 | vrátit `1 if trade.get("win") else 0` | **KILLED** | `unknown win was coerced to 0` |

M4 je klíčový: dokazuje, že kontrakt `compute_win_rate` nelze rozšířit z
„vyluč ne-obchody" na „vyluč prohry", aniž to test okamžitě chytí.
Po každém mutantu ověřeno, že `git diff HEAD` pro dotčené zdroje je prázdný.

### R2-E — Testy

```text
199 passed, 2 failed, 9 skipped
```

Obě selhání jsou **pre-existing** a v souborech, kterých se tato práce
nedotkla: `test_f8b_integration::test_tick_hook_before_blacklist_gate_and_gated`
(substring probe do `signal_generator.py`) a
`test_sec_01_dashboard_boundary::test_spa_handler_only_serves_fixed_index`
(`bytes` vs `str`).

> **NEOPRAVENO — zaznamenáno poctivě.** Devět selhání
> (`test_observe_gate_choke` ×5, `test_learning_hook_evidence_collection` ×4)
> v kombinovaném běhu **prochází**, ale samostatně stále **selhává**
> (`paper_state_not_ready`). Jde o pre-existing **závislost na pořadí testů** —
> dřívější test nechá `_PAPER_STATE_STATUS` v READY — nikoli o něco, co tato
> změna opravila. Ověřeno samostatným spuštěním obou souborů.

### R2-F — Aktuální evidence (nezměněná interpretace)

| Okno | raw n / WR | qualified n / WR | excluded | reconciles |
|---|---|---|---|---|
| recent-100 | 100 / **48,00 %** | 75 / **64,00 %** | 25 | `100 == 75+25` ✓ |
| celá DB | 472 / **48,73 %** | 366 / **62,84 %** | 106 | `472 == 366+106` ✓ |

Varování z hlavní části platí beze změny: **64 % NENÍ splnění cíle.** Kohort je
39,8 dne starý, obsahuje 116 syntetických řádků, předchází všem opravám této
relace a není versionově homogenní. Podmínky Fáze 4 (1), (3) a (5) nejsou
splněny. Nově zavedené `code_version`/`config_version` sloupce jsou u všech
472 historických řádků `NULL` — teprve budoucí closy je ponesou, což je právě
ten důvod, proč versionově homogenní kohort zatím **neexistuje**.

### R2-G — Commity (větev `wr50/canonical-single-path-phase2`)

| Commit | Obsah |
|---|---|
| `2d68876` | Fáze 2 canonical admission wrapper (9 call-siteů) |
| `b35caf8` | Report Round 1 |
| `6fcfee8` | Separace testovacího sinku |
| `3be656a` | Schema migrace + end-to-end persistence attribution |
| `f01b19f` | Fáze 3 — VOID stav |

Ownership caveat z hlavní části stále platí pro `paper_trade_executor.py`,
`realtime_decision_engine.py`, `trade_executor.py` a `dashboard_web.py`.
Nově dotčené `src/core/trade_metrics_contract.py`,
`src/services/local_persistent_cache.py` a `tests/conftest.py` obsahují
**pouze** práci této relace.

### R2-H — Počty (kumulativně za celou relaci)

```text
REAL orders                         = 0
deployments / restarts / kills      = 0
SSH commands                        = 0   (live identity NOT_VERIFIED)
external/network calls              = 0
git push                            = 0
git reset --hard / git checkout <path> = 0
local commits                       = 5 (větev, ne main)
production SQLite writes            = 1 accidental + 1 corrective revert
                                      (disclosed in R2-A; net zero, 472 -> 472)
```

### R2-I — Přesný další krok

1. **Fáze 4 nelze začít hned**: versionově homogenní kohort vznikne teprve poté,
   co poběží nové closy nesoucí `code_version`/`config_version`. Do té doby
   je jakékoli tvrzení o WR >50 nepodložitelné.
2. Zbývá **oddělit testovací sink i pro `learning_database.sqlite`** a
   `paper_open_positions.json` — tato relace uzavřela pouze `cache.sqlite`.
3. Opravit pre-existing závislost na pořadí testů (`_PAPER_STATE_STATUS`
   leak), jinak zůstane 9 testů falešně zelených v kombinovaném běhu.
4. Teprve pak Fáze 4 shadow kohorta s předem zafixovaným
   `code_version`/`config_version`, minimální velikostí vzorku, holdout oknem
   a max-loss capem.

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.

---
---

## Round 3 — všechny zbývající sinky + závislost na pořadí testů

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
Release gate: `NOT_READY_FOR_DEPLOYMENT`. Deploy/restart/SSH/REAL orders: `0`.

### R3-A — `cache.sqlite` nebyl zdaleka jediný sink

Stejný vzorec (cesta rozhodnutá z module-level konstanty při importu) platil
ještě pro tři další sinky:

| Modul | Sink | Riziko |
|---|---|---|
| `local_learning_storage` | `learning_database.sqlite` | **síťový disk**, viz R3-B |
| `paper_trade_executor` | `data/paper_open_positions.json` | živý stav otevřených pozic |
| `paper_adaptive_learning` | `server_local_backups/paper_adaptive_learning_state.json` | **durable naučené parametry** (~70 kB), z nichž dashboard počítá lifetime metriky |

Že šlo o známý hazard, leží přímo na disku: dřívější audit vedle toho souboru
nechal `o1a1b_audit_20260525T082414Z/state_hash_before_tests.txt` a kopii
`.before_validation.json` — tedy někdo si před spuštěním testů stav
**ručně hashoval a obnovoval**. Tato změna ten rituál nahrazuje strukturální
zárukou.

### R3-B — `local_learning_storage` nebyl CWD-relativní, ale síťový

Nález, který změnil podobu opravy: tento modul nejdřív **prohledává
`NETWORK_PATHS`**, a na tomto stroji je `\\MYCLOUD-G07Y2M\Public\Cryptomaster`
skutečně připojen — takže `DB_PATH` se rozhodoval na **sdílené síťové úložiště**,
nikoli do repa. Test zapisující tento sink by poškodil data, která čtou jiné
stroje.

Otázka „je to uvnitř repa?" je proto příliš slabá. Vynucovaný invariant je
silnější:

> pod pytestem musí **každý** sink vycházet uvnitř dočasného session rootu

To platí bez ohledu na to, zda je produkční cíl podadresář repa, absolutní
`/opt` cesta nebo připojený UNC share.

### R3-C — Jedno pravidlo, ne N kopií

Guard žije v jediném místě `src/core/test_sink_guard.py`. Tento projekt má
zdokumentovanou regresi způsobenou tím, že dvě funkce četly stejný parametr
s odlišnými defaulty (WR 57 % → 0 %); N ručně opsaných kopií bezpečnostního
guardu je tentýž hazard s horšími následky.

Produkční běh není dotčen: `PYTEST_CURRENT_TEST` tam není nastaven, takže každé
volání guardu je no-op. `local_learning_storage` override se navíc čte **před**
network probe, takže přesměrovaná session se síťového disku nedotkne.

### R3-D — Přesměrování konstant bylo nutné, ale NEdostatečné

`tests/test_p1_paper_exploration.py` pracoval se stavovým souborem přes
**39 natvrdo zapsaných literálů** `"data/paper_open_positions.json"`, čímž
`_STATE_FILE` obcházel úplně.

> **DISCLOSURE — druhá vlastní kontaminace.** Právě tyto literály během
> celosuitového běhu v této relaci **smazaly** reálný
> `data/paper_open_positions.json`. Soubor byl obnoven do pozorovaného
> původního stavu (`{}`) a hash ověřen zpět na `44136fa355b3678a`.
> Je gitignorovaný, takže smazání se neprojevilo v `git status` — nalezeno
> pouze proto, že se před i po běhu porovnávaly SHA-256 produkčních souborů.

Literály nyní čtou přesměrovanou konstantu; všechny assertions zůstávají
identické (jde o tentýž soubor, který executor zapisuje).

**Poučení:** sink separace na úrovni modulových konstant nechrání před
natvrdo zapsanými cestami v testech. Proto je fail-closed guard nutný jako
druhá vrstva, ne jako zdvojení té první.

### R3-E — Závislost na pořadí testů (falešná zeleň)

`open_paper_position()` je fail-closed, dokud `_PAPER_STATE_STATUS` není
`READY`, a modul se záměrně neinicializuje při importu
(`test_state_01_import_purity` to vynucuje). Status tedy byl tím, co po sobě
nechal předchozí test.

Devět testů proto **procházelo v kombinovaném běhu a selhávalo samostatně** —
falešná zeleň: kombinovaný průchod nedokazoval nic o testovaném kódu, jen
o pořadí kolekce.

Autouse fixture nyní fixuje výchozí bod na `READY`, což je stav, se kterým
produkce reálně běží (`_init_paper_state_once()` tam běží při startu). Import
purity zůstává zachována: fixture modul **nikdy neimportuje** a je no-op,
pokud si jej test sám nenaimportoval. Testy not-ready cest si status nadále
monkeypatchují samy.

### R3-F — Baseline změřen, nikoli odhadnut

Aby bylo poctivě rozlišeno „pre-existing" od „způsobeno mnou", byl vytvořen
git worktree na commitu `f01b19f` a spuštěn s `FORCE_LOCAL_STORAGE`, takže
nemohl sáhnout ani na NAS, ani na tento repozitář:

| Běh (identická dvojice souborů) | failed | passed |
|---|---|---|
| baseline `f01b19f` | **30** | 45 |
| tato větev | **24** | 51 |

**Šest opraveno, žádná regrese.** Zbývajících 24 je pre-existing.
Worktree byl poté odstraněn; produkční soubory hlavního repa ověřeny jako
nedotčené.

### R3-G — Mutation-kill (Round 3)

| # | Mutace | Výsledek | Zabito assertion |
|---|---|---|---|
| M6 | `assert_not_production_sink()` degradován na no-op | **KILLED** (2 nezávislé sady) | `DID NOT RAISE <class 'RuntimeError'>` |

Dokazuje, že guard není vacuous. Po revertu ověřeno, že `git diff HEAD` pro
dotčené zdroje je prázdný.

### R3-H — Testy a důkaz nekontaminace

```text
207 passed, 2 failed, 9 skipped
```

Obě selhání jsou pre-existing v nedotčených souborech
(`test_f8b_integration` substring probe do `signal_generator.py`,
`test_sec_01_dashboard_boundary` bytes/str).
`tests/test_state_01_import_purity.py` **prochází** — fixture import purity
neporušila.

SHA-256 všech tří produkčních datových souborů ověřeny **před i po** běhu:

| Soubor | SHA-256 (prefix) | Stav |
|---|---|---|
| `local_learning_storage/cache.sqlite` | `d0dd9e8a2348754f` | UNCHANGED |
| `server_local_backups/paper_adaptive_learning_state.json` | `9263583f87369276` | UNCHANGED |
| `data/paper_open_positions.json` | `44136fa355b3678a` | UNCHANGED |

### R3-I — Počty (kumulativně za celou relaci)

```text
REAL orders                         = 0
deployments / restarts / kills      = 0
SSH commands                        = 0   (live identity NOT_VERIFIED)
external/network calls              = 0
git push                            = 0
git reset --hard / git checkout <path> = 0
local commits                       = 7 (větev, ne main)
git worktree                        = 1 vytvořen a odstraněn (read-only baseline)
production data writes              = 2 accidental, obě revertovány a hash-ověřeny
                                      (R2-A jeden řádek v cache.sqlite;
                                       R3-D smazaný paper_open_positions.json)
```

### R3-J — Zbývá otevřené

1. **24 pre-existing selhání** v `test_p1_paper_exploration.py` (ověřeno jako
   pre-existing proti baseline). Nejde o blokátor Fáze 4, ale je to reálný dluh.
2. Fáze 4 stále čeká na akumulaci nových closes s vyplněným
   `code_version`/`config_version`. **Nelze uspíšit.**
3. Ostatní testy mohou obsahovat další natvrdo zapsané produkční cesty;
   auditován byl pouze `data/paper_open_positions.json` vzorec. Guard je proti
   nim fail-closed, ale samotný sken proveden nebyl.

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.

---

## 3. CLAUDE_SINGLE_PATH_POLICY_2026-09-14.md

*(architektonický mandát — plné znění)*

# Single-path bot policy

Požadavek: bot nesmí získávat další strategické nebo obchodní větve.

### Kanonický tok

`signal -> canonical admission -> open_paper_position -> one close writer -> metrics`

Všechny zdroje signálů (`rde_take`, `training_sampler`, exploration a legacy
callery) mají být pouze metadata stejného toku. Nesmí existovat samostatné
rozhodování, které by obcházelo canonical admission nebo měnilo denominator.

### Pravidla

- jeden admission kontrakt s výsledkem `OPENED | BLOCKED`;
- jeden persistence acknowledgement pro open i close;
- jeden exit taxonomy a jeden metrics loader;
- source/regime/strategy jsou štítky, ne nové obchodní větve;
- žádné nové bypassy, allowlisty ani speciální fallback větve;
- změny se nejdříve ověří paper-only testem a shadow kohortou.

### Aktuální stav

Repo stále obsahuje několik historických call-siteů `open_paper_position()`.
V tomto kroku nebyla provedena riskantní refaktorizace; release gate zůstává
zavřený. Další implementace musí nejprve vytvořit production-linked RED test,
poté přesunout call-sitey pod jediný canonical wrapper a odstranit duplicity.

*(Poznámka 2026-09-15: tato poslední věta popisuje stav PŘED Fází 2 —
canonical wrapper mezitím vznikl, viz Sekce 2 výše.)*

---

## 4. WR_TARGET_ANALYSIS_2026-09-14.md

*(⚠️ RETRAHOVANÁ ANALÝZA — ponecháno pro dohledatelnost, NECITOVAT jako platnou evidenci; viz F0-C výše)*

# WR >50 analýza (paper-only)

### Zjištění

Lokální databáze obsahuje 472 uzavřených obchodů. V posledních 100:

- `training_sampler`: 18/60 WIN = 30,0 %
- `rde_take`: 30/40 WIN = 75,0 %
- agregovaně: 48/100 = 48,0 %

Kanonické zdroje za celý lokální snapshot mají 229/412 WIN = 55,58 %,
ale jde o smíšené období a nikoli o live/post-fix kohort.

### Bezpečný závěr

Největší pozorovaný pokles WR přichází z `training_sampler` v recent-100.
Pouhé odstranění tohoto zdroje by zvýšilo vykazovaný WR, ale současně by změnilo
denominator a zastavilo sběr tréninkové evidence. Taková změna nesmí být
provedena jako dashboardový trik ani bez versionovaného experimentu.

### Doporučený experiment

1. PAPER-only shadow kohorta se stejnými signály a immutable attribution.
2. Randomizované/časově oddělené porovnání `training_sampler` vs. `rde_take`.
3. Předem stanovené minimum vzorku, confidence interval a max-loss cap.
4. Teprve po čistém kohortu rozhodnout, zda snížit admission rate
   `C_WEAK_EV_TRAIN`, upravit TP/SL nebo změnit segmentové cooldowny.
5. Dashboard musí zobrazovat all-source WR i source-scoped WR odděleně.

### Stav

Nebyla provedena změna admission prahů, denominatoru ani live konfigurace.
Nebyl proveden deploy, restart nebo REAL order. Cíl WR >50 proto zůstává
experimentální acceptance criterion, nikoli garantovaný stav.

Požadavek na jednoduchý bot je závazný: další práce nesmí přidávat větve.
Zdroje signálů budou pouze štítky v jednom canonical admission toku.

**⚠️ Retrakce (Fáze 0, viz Sekce 2 F0-C výše):** okno „recent-100" použité
zde pokrývá jen 34 minut z 40 dní staré, 24,6 % kontaminované DB. Čísla
75 %/30 %/48 % **nejsou platná evidence** a nesmí se dál citovat. Doporučený
experiment (sekce výše) zůstává metodicky správný a je přesně to, co Fáze 4
má provést — jen na čistém, ne na tomto kohortu.

---

## 5. CLAUDE_WR50_SINGLE_PATH_IMPLEMENTATION_PROMPT_2026-09-14.md

*(původní zadání pro celou tuto práci — plné znění, 197 řádků)*

# Claude implementation prompt — WR >50 bez větvení botu

### Role a cíl

Jsi seniorní Python/quant/reliability engineer. Pracuj autonomně v repozitáři
`C:\Projects\CryptoMaster_srv` a postupuj až do dosažení měřitelného výsledku.

Primární cíl: zvýšit skutečný paper-only win rate nad 50 % v čistém,
versionovaném post-fix kohortu při současně nezáporném P&L.

WR nesmí být zvýšen změnou denominátoru, filtrováním ztrát, přepisem historie,
změnou API pouze pro zobrazení nebo vyřazením neúspěšných obchodů z evidence.
Pokud data cíl nepotvrdí, výsledek musí zůstat `NOT_ACHIEVED`.

### Nezměnitelné bezpečnostní hranice

- Výhradně PAPER režim. Nikdy nepovoluj REAL orders, exchange execution,
  live trading ani produkční zápisy.
- Žádné SSH změny, restart, deploy, migrace, mazání runtime dat nebo cleanup
  mimo explicitně vytvořený temp prostor bez samostatného schváleného gate.
- SSH je nejprve pouze read-only inventura: SHA, systemd stav, bind/auth,
  health endpoint a metriky. Tajné hodnoty, credentialy a API tokeny nikdy
  nečti ani nevypisuj.
- Chráněné runtime/SQLite/WAL/SHM soubory nekopíruj, nehashuj a nemaž.
- Každý příkaz používej s `rtk` prefixem. Nepoužívej `git reset --hard`,
  `git checkout`, broad delete ani blind restart.
- Před produkčním importem nebo testem aktivuj síťové, procesní, threadové,
  filesystemové a SQLite guardy v izolovaném child procesu.
- Při neočekávaném order/socket/DNS/HTTP/process/thread/write/secret hitu
  okamžitě zastav dynamické provádění a uveď přesný incident.

### Architektonická zásada: žádné nové větve

Bot musí mít jediný obchodní tok:

`signal -> canonical admission -> open_paper_position -> one close writer -> metrics`

`rde_take`, `training_sampler`, exploration a legacy callers jsou pouze
atributy/zdroje stejného toku. Nesmí vytvářet samostatné rozhodovací větve,
bypassy, speciální allowlisty, timeout výjimky ani druhý persistence writer.

Požadovaný canonical kontrakt:

- jedna funkce vrací `OPENED` nebo `BLOCKED` s přesným důvodem;
- jeden immutable `segment_key` při open i close;
- jeden `effective_hold_s` kontrakt pro tick i scanner;
- jeden close/learning/outbox acknowledgement;
- jedna kanonická exit taxonomie včetně všech `TIMEOUT_*` variant;
- source/regime/side/profile jsou pouze data, nikoli nové větve.

### Fáze 0 — baseline a evidence

1. Zmapuj všechny call-sitey open/close/admission, včetně function-local
   importů. Vytvoř literální inventory a ownership mapu.
2. Změř baseline bez úprav: recent-100, recent-500, lifetime, source, symbol,
   side, regime, bucket, exit reason, P&L a denominator.
3. Rozděl kohorty podle `code_version`, `config_version`, `segment_key` a
   admission route. Legacy NULL attribution zůstává `UNQUALIFIED`.
4. U každého výsledku uveď `n`, wins, WR, P&L, interval nejistoty a časové
   období. Smíšené historické/live hodnoty nikdy neslučuj.
5. Zaznamenej aktuální release gate a dirty ownership. Neprováděj deploy,
   dokud není vytvořen immutable artefakt s manifestem a rollbackem.

### Fáze 1 — production-linked RED testy

Před každým source editem musí existovat samostatný RED test proti aktuálnímu
production-linked source. Setup/import/guard chyba není RED.

Povinné RED oblasti:

- loader failure/reconcile pending nesmí vést k READY ani subscription;
- direct open v `UNINITIALIZED`, `INITIALIZING`, `SUBSCRIBING`, `FAILED` musí
  vrátit přesně `paper_state_not_ready` bez side effectů;
- open save failure musí rollbackovat pozici, cooldown, telemetry, bridge,
  outbox a log acknowledgement;
- close/removal/timeout/quarantine save failure nesmí potvrdit úspěšný close;
- concurrent open musí být single-writer lineární, bez phantom pozice;
- subscription failure a same-thread re-entry nesmí vytvořit ghost registration;
- všechny callers musí zpracovat výsledek canonical open.

Použij skutečný SUT, ne kopii modelu. Každý RED musí mít paired READY control,
přesný expected reason a business assertion.

### Fáze 2 — canonical admission a attribution

1. Zaveď jediný admission wrapper a postupně pod něj převeď všechny call-sitey.
2. Při open povinně persistuj `source`, `symbol`, `side`, `regime`,
   `tp_sl_profile`, `segment_key`, `code_version`, `config_version`,
   `admission_route`, `admission_reason`, `effective_hold_s`.
3. Při close zachovej přesně stejné hodnoty a přidej exit taxonomy, MFE/MAE,
   hold duration a writer version.
4. Chybějící attribution nikdy nedoplňuj odhadem; segment je `UNQUALIFIED`.
5. Gate je fail-closed při chybě historie, schématu nebo persistence.
6. Evidence route může sbírat PAPER data s capy, ale nikdy se nesmí označit
   jako STRICT/READY/REAL.

### Fáze 3 — exit/TP-SL/timeout kontrakt

- Validuj finální TP/SL až po kalibraci a cost-floor clampu.
- Invalidní geometrii neproměňuj tiše na timeout-only; pozici karantenizuj.
- Sjednoť tick a scanner na jeden `effective_hold_s`.
- TP/SL na hraničním ticku má prioritu před timeoutem.
- Scanner buď skutečně běží nezávisle na price ticku, nebo dokumentaci
  oprav tak, aby netvrdila opak.
- Oprav dead dict iteration v nouzovém close loopu.
- Přidej fake-clock testy pro TP, SL, exact timeout, invalid levels, restart,
  rehydration a exactly-once close.

### Fáze 4 — WR experiment, ne manipulace metrik

Nejprve spusť PAPER shadow kohortu se stejnými signály a jediným canonical
admission tokem. Porovnej `training_sampler` a `rde_take` bez vyřazení řádků.

Experiment musí mít:

- předem zafixovaný config/code version;
- minimální velikost vzorku a confidence interval;
- max-loss cap a automatický rollback configu;
- stejné exit/fee/timeout podmínky;
- oddělené all-source, source-scoped a qualified-only dashboard metriky;
- raw input count == součet všech mutually-exclusive bucketů;
- `OTHER/UNKNOWN` bucket pro každý neznámý exit/source/version.

WR >50 je přijatelné pouze pokud:

1. kohorta je post-fix a versionově homogenní;
2. denominator je explicitní a všechny vstupy jsou zahrnuté;
3. WR >50 je reprodukovatelný na předem určeném holdout okně;
4. P&L je po poplatcích nezáporné;
5. nejsou přítomny unresolved NULL attribution, duplicate closes nebo
   ztracené exit rows;
6. strict/readiness/REAL gate zůstávají zavřené, dokud to výslovně neschválí
   samostatný deployment review.

### Fáze 5 — dashboard/API

Dashboard nesmí měnit výpočet kvůli cíli WR. Zobrazuj minimálně:

- `win_rate_pct`, `win_rate_window`, `win_rate_basis`, `win_rate_scope`,
  `win_rate_denominator`;
- canonical source-scoped WR/P&L;
- count `UNKNOWN/UNQUALIFIED/OTHER`;
- code/config version a timestamp freshness;
- all-source metriky odděleně od qualified/post-fix kohort.

API alias `/api/metrics` může sdílet stejný handler, ale nesmí obcházet auth.
Přidej statické kontraktní testy i paper-only endpoint testy.

### Fáze 6 — testy a mutation-kill

Po každém fixu spusť jen explicitní paper-only node IDs:

- unit/contract tests canonical admission;
- open/close persistence acknowledgement;
- concurrency/barrier tests;
- timeout/TP-SL fake-clock matrix;
- metrics reconciliation;
- dashboard/API contract;
- mutation test každého původního bug invariantu.

Mutant musí nejprve projít čistým baseline importem a poté selhat pouze
expected assertion. SyntaxError, ImportError, timeout, guard failure nebo
no-op transform není killed mutant.

### Fáze 7 — immutable release gate

Deployment je povolen pouze pokud:

- chráněné production paths jsou vlastnicky reconciled a čisté;
- existuje immutable artefakt s SHA-256 manifestem všech zdrojů;
- paper smoke evidence je přiložena a reprodukovatelná;
- rollback artefakt je připraven a otestován;
- dashboard auth/bind/systemd hardening je ověřen odděleně;
- host SHA, running process SHA a deployed SHA jsou potvrzeny read-only
  inventurou nebo zůstávají `NOT_VERIFIED`;
- žádný REAL order ani produkční zápis nebyl použit jako test.

Pokud gate selže, výsledek je `NOT_READY_FOR_DEPLOYMENT`; nesmíš jej obcházet.

### Povinný finální report

Vytvoř vždy nový `CLAUDE_*.md` report s:

- baseline vs. remediation status v oddělených dimenzích;
- přesnými command/node IDs, exit codes a počty pass/fail/skip;
- seznamem změněných souborů a ownership caveat;
- WR/P&L tabulkou s denominatorem, kohortou a intervalem;
- mutation-kill důkazem;
- release gate stavem;
- runtime metadata/content stavem jako `NOT_VERIFIED`, pokud nebyl bezpečně
  měřen;
- počty REAL orders/external calls/production writes/deployments;
- residual risks a přesným dalším krokem.

Nikdy netvrď „WR >50 dosaženo", pokud podmínky výše nejsou splněny. Platné
terminální stavy jsou `ACHIEVED`, `PARTIAL`, `NOT_ACHIEVED`, `BLOCKED_BY_SCOPE`
nebo `NOT_VERIFIED`; žádné hybridní statusy.

---

## 6. tools/release_gate.py

*(zdrojový kód + aktuální výstup, 2026-09-15)*

```python
"""Fail-closed release gate for PAPER deployment.

The gate is intentionally read-only. It never stages, commits, copies, restarts,
or contacts a host. A deployment wrapper may proceed only after this command
returns zero and an immutable artifact has been created separately.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    "src/services/paper_trade_executor.py",
    "src/services/realtime_decision_engine.py",
    "src/services/trade_executor.py",
    "src/services/dashboard_web.py",
    "systemd/cryptomaster-dashboard.service",
)


def _git_status() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *PROTECTED],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _hashes() -> dict[str, str]:
    out = {}
    for rel in PROTECTED:
        path = ROOT / rel
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[rel] = digest
    return out


def evaluate(artifact: Path | None = None, smoke_evidence: Path | None = None) -> tuple[bool, list[str], dict[str, str]]:
    reasons: list[str] = []
    statuses = _git_status()
    if statuses:
        reasons.append("protected_paths_dirty")
    hashes = _hashes()
    missing = [rel for rel in PROTECTED if rel not in hashes]
    if missing:
        reasons.append("missing_protected_files:" + ",".join(missing))
    if artifact is None or not artifact.is_file():
        reasons.append("immutable_artifact_not_created")
    if smoke_evidence is None or not smoke_evidence.is_file():
        reasons.append("paper_smoke_evidence_not_attached")
    return False, reasons, hashes             # <-- SUSPECTED BUG: hardcoded False,
                                                #     not `len(reasons) == 0`. See
                                                #     Section 1, §0.1 above. NOT patched
                                                #     by the session trying to pass it.


def main() -> int:
    parser = argparse.ArgumentParser(description="read-only fail-closed PAPER release gate")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--artifact", type=Path, help="path to externally-created immutable release artifact")
    parser.add_argument("--paper-smoke-evidence", type=Path, help="path to attached paper-only smoke evidence")
    args = parser.parse_args()
    ready, reasons, hashes = evaluate(args.artifact, args.paper_smoke_evidence)
    if args.json:
        import json
        print(json.dumps({"ready": ready, "reasons": reasons, "hashes": hashes}, sort_keys=True))
    else:
        print("RELEASE_READY=" + ("YES" if ready else "NO"))
        for reason in reasons:
            print("REASON=" + reason)
        for path, digest in hashes.items():
            print(f"SHA256={digest} FILE={path}")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

**Aktuální výstup (2026-09-15, na `wr50/canonical-single-path-phase2`, po
vyřešení `protected_paths_dirty` a přiložení obou artefaktů ze Sekce 7):**

```json
{
  "hashes": {
    "src/services/dashboard_web.py": "854058962387bca3e613e2b0c8ac2b9861123e8a40c79d9f0a2d3cc8b1292da9",
    "src/services/paper_trade_executor.py": "f1cd7206e88146c1239f661d400f2ff9089e174bb19f0f0336778adcfec3b60e",
    "src/services/realtime_decision_engine.py": "94d730681529e5507d52cd2f0ca4786270af4d4d30258d0a884e5f503123b4bf",
    "src/services/trade_executor.py": "dec895b4be1b619f6af02060c35a8ac75a8b3452d105c9d04dec960abfc46315",
    "systemd/cryptomaster-dashboard.service": "0eb16d0633e16ce77075b5ab7ca242d0988ee8d4ced3ba32eb1ce1dc7caf888e"
  },
  "ready": false,
  "reasons": []
}
```

Příkaz:
```
python tools/release_gate.py --json \
  --artifact release_artifacts/wr50_phase2_manifest_2026-09-15.json \
  --paper-smoke-evidence release_artifacts/wr50_phase2_paper_smoke_evidence_2026-09-15.txt
```

`reasons` je prázdné pole — všechny tři skriptem kontrolované podmínky jsou
splněny. `ready` přesto čte `false` a exit kód zůstává `2`. Viz komentář ve
zdrojovém kódu výše a Sekce 1 §0.1 pro plný kontext a otázku k rozhodnutí.

---

## 7. Release artefakty

Oba soubory existují na větvi `wr50/canonical-single-path-phase2`
(`release_artifacts/`), commitnuté a pushnuté:

- `wr50_phase2_manifest_2026-09-15.json` — SHA-256 manifest všech 5 chráněných
  souborů, commit identity, explicitní scope a explicitní vyloučení (dashboard
  hardening draft, viz Sekce 1 §0.1).
- `wr50_phase2_paper_smoke_evidence_2026-09-15.txt` — čerstvý běh 61 cílených
  testů + odkaz na již zdokumentovaný běh 207 testů a 6 zabitých mutantů
  (Sekce 2, Round 3).

Odložený návrh (NE commitnutý, NE součást release gate):
`_workspace/52_uncommitted_dashboard_hardening_preserved_20260915.service.txt`
— plné znění hardeningu dashboardu, viz Sekce 1 §0.1 pro kontext a otevřenou
otázku k rozhodnutí.

---

*Konec balíčku. Všech 7 sekcí odpovídá přesně tomu, co
`EXTERNAL_AUDIT_WR50_SINGLE_PATH_PROMPT_2026-09-14.md` cituje jménem. REAL
trading = absolutní NO-GO nezávisle na čemkoli výše.*
