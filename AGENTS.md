# AGENTS.md — pravidla pro Codex a další kódovací agenty

Projekt: **CryptoMaster** — papírový (PAPER) obchodní bot pro krypto, Python.
Komunikace s uživatelem a reporty: **česky**. Identifikátory a kód: anglicky.

## Aktuální zadání

**Otevřené zadání:** `docs/codex_prompts/CODEX_REREVIEW_MICRO_RECORDER_R3_2026-11-26.md` (rev. 3: stop-tick jen v ověřeném stavu, pevné cíle mimo test režim, preflight bez zápisu, rollback/úklid testy; report `_workspace/2026-11-26_codex_rereview_micro_recorder_r3.md`). Dřív `docs/codex_prompts/CODEX_REREVIEW_MICRO_RECORDER_R2_2026-11-26.md` → `_workspace/2026-11-26_codex_rereview_micro_recorder_r2.md` (CHANGES_REQUIRED → opraveno) (rev. 2: liq_sampled, disk_skip gap, samostatný stop-tick bez mazání logu, připnutý fázovaný deploy skript; report `_workspace/2026-11-26_codex_rereview_micro_recorder_r2.md`). Dřív `docs/codex_prompts/CODEX_REVIEW_MICRO_RECORDER_DESIGN_2026-11-26.md` → `_workspace/2026-11-26_codex_review_micro_recorder_design.md` (CHANGES_REQUIRED → opraveno) (návrh sběrače order booku + likvidací, limity, vypnutí nefunkčního tick-recorderu; report `_workspace/2026-11-26_codex_review_micro_recorder_design.md`). Hotové 2026-11-26: `_workspace/2026-11-26_codex_review_event_screen_result.md` (EVENT screen přijat, E1/E2 NO_EDGE; doporučení: přeformulovat cíl, případně nejdřív sbírat order book / likvidace). Hotové: `_workspace/2026-11-26_codex_rereview_event_screen_protocol_r3.md` (APPROVE_TO_RUN). Dřív `docs/codex_prompts/CODEX_REREVIEW_EVENT_SCREEN_PROTOCOL_R2_2026-11-26.md` (EVENT screen rev. 2:
nulový bootstrap explicitně, fail-closed úplnost 476 archivů, TRAIN jen popisně; report
`_workspace/2026-11-26_codex_rereview_event_screen_protocol_r2.md`). Dřív: `_workspace/2026-11-26_codex_review_event_screen_protocol.md`
(CHANGES_REQUIRED → opraveno).
Hotové 2026-11-26: `_workspace/2026-11-26_codex_review_stonkfly_c1_result.md` (C1 ACCEPT +
APPROVE, přepis verdiktu; Stonkfly zůstává shadow, C2 jen jako volitelný výzkum plasticity, C3 ne bez nové hypotézy).
Dřív 2026-11-26: `_workspace/2026-11-26_codex_rereview_stonkfly_c1_protocol_r3.md` (APPROVE_TO_RUN);
`_workspace/2026-11-26_codex_rereview_stonkfly_c1_protocol_r2.md` (CHANGES_REQUIRED R2.1–R2.3 → opraveno v rev. 3);
`_workspace/2026-11-25_codex_review_stonkfly_c1_protocol.md` (A2 report APPROVE; C1 CHANGES_REQUIRED → opraveno v rev. 2).
Hotové 2026-11-25: `_workspace/2026-11-25_codex_review_stonkfly_a2_result.md` (A2 ACCEPT_MEASURED; výklad CHANGES_REQUIRED → opraveno;
další krok C1 offline relativní dekodér → C2 tiché KC → C3 mapování). Dřív 2026-11-25: `_workspace/2026-11-25_codex_decide_stonkfly_a2_production_cgroup.md`
**REJECT** A2 na produkci v cgroup (preflight chce 2,5 GiB, dostupné 2,2 GiB; limit nerezervuje RAM/CPU pro bota). A2 jen na
izolovaném 8GB Linuxu (nejdřív `--smoke`), jinak odložit a produkci posoudit znovu až po měřicím okně (po 2026-12-02 09:00 UTC).
Ověřený balíček pro A2: lokálně `C:\Projects\_stonkfly_a2_bundle\` (23/23 hashů dle manifestu). Dřív 2026-11-25: release „exit-taxonomy“ **nasazen 08:10:48 UTC** po APPROVE
`_workspace/2026-11-25_codex_rereview_exit_taxonomy_d6_d7.md` (INSTALL_OK, PID bota beze změny; viz `docs/OPERATING_STATE.md`).
Dřív: `_workspace/2026-11-25_codex_rereview_exit_taxonomy_d4_d5.md` (CHANGES_REQUIRED → opraveno); `_workspace/2026-11-25_codex_rereview_exit_taxonomy_deploy_step.md`
(CHANGES_REQUIRED → opraveno); `_workspace/2026-11-25_codex_rereview_exit_taxonomy.md` (kód + postimage schváleny,
postup CHANGES_REQUIRED → opraveno); `_workspace/2026-11-24_codex_review_exit_taxonomy_and_threshold.md`
(A CHANGES_REQUIRED → opraveno; B práh −25 bps ponechat, okno zapsané v OPERATING_STATE). Dřív 2026-11-24: `_workspace/2026-11-24_codex_rereview_stonkfly_a2_r1_r3.md` **APPROVE**
protokolu A2 pro jeden baseline běh na dočasném izolovaném stroji (nejdřív `--smoke` = `SMOKE_OK`; závěr jen z `MEASURED`
s prázdným `incomplete`/`errors`; prahy se po běhu nemění). Čeká se na server od operátora. Dřív: `docs/codex_prompts/CODEX_REREVIEW_STONKFLY_A_PIN_DTYPE_2026-11-24.md`
→ `_workspace/2026-11-24_codex_rereview_stonkfly_a_pin_dtype.md` **APPROVE** statické části Stonkfly fáze A (R1–R6; lokální,
necommitnuté); A2 (běh sítě na kontrolních snímcích, R8) zůstává otevřené a čeká na schválené prostředí. Dřív: re-review `_workspace/2026-11-24_codex_rereview_r5_and_stonkfly_a.md` (A: R5 APPROVE kódu, bez nasazení
a bez `ALLOW_OPEN_POSITIONS=1`; B: CHANGES_REQUIRED pin bez dtype, opraveno); re-review R4 `_workspace/2026-11-24_codex_rereview_allow_open_positions_r4.md` CHANGES_REQUIRED R5
a review fáze A `_workspace/2026-11-24_codex_review_stonkfly_phase_a.md` CHANGES_REQUIRED S1, obojí opraveno;
dřív A1, R1–R4, review `_workspace/2026-11-23_codex_review_r4_and_stonkfly_off.md` (A CHANGES_REQUIRED, opraveno;
B vypnutí Stonkfly SUPERSEDED, změny nástroje vráceny — Stonkfly se nevypíná);
povolení do schválení nepoužívat).
Hotové: omezení výpisů ECON BAD **nasazeno 2026-11-23 11:54:37 UTC** (kohorta `econ-bad-log-limit`, viz `docs/OPERATING_STATE.md`);
nasazovací krok APPROVE `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d6d8.md`, dřívější kola D1–D8 opravena.

Hotové: review nasazovacího kroku stropu bucketu → APPROVE
(`_workspace/2026-11-23_codex_review_bucket_cap_deploy_step.md`); strop **nasazen 2026-11-23 07:45:02 UTC**
(kohorta `explore-bucket-cap`, `cohort_start_ms = 1795419902000`, viz `docs/OPERATING_STATE.md`).
Neblokující P2/P3 z review (síťová izolace sandboxu, zastaralý komentář o „execution paths“
v `deploy_bot_files.sh`) zůstávají na příští změnu nástroje.

Hotové: re-review B4 → APPROVE (`_workspace/2026-11-19_codex_rereview_outbox_deploy_b4.md`); outbox
**nasazen 2026-11-19 14:15:30 UTC** (`DEPLOY_outbox-visibility APPLIED OK`, bot PID 1634146).
Hotové: `_workspace/2026-11-19_codex_rereview_post_c1_deploy_and_bucket_cap.md`: dashboard APPROVE
(nasazovací krok; **nasazeno 2026-11-19 14:00 UTC**, readiness = `paper_only`), strop bucketu APPROVE (kód a artefakt, ne nasazení), outbox CHANGES_REQUIRED (B4,
opraveno). Runbook `docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md`.
Dřívější kola (opraveno): `_workspace/2026-11-19_codex_review_post_c1_deploy_step.md` (CHANGES_REQUIRED),
`_workspace/2026-11-19_codex_review_explore_bucket_cap.md` (REJECT).

Hotové: re-review plánovače kolo 4 + conftest kolo 2 → APPROVE (kód; plánovač zůstává vypnutý,
schválení se netýká aktivace ani nasazení), `_workspace/2026-11-19_codex_rereview_planner_r4_conftest_guard_r2.md`.
Dřívější kola (CHANGES_REQUIRED, opraveno): `_workspace/2026-11-19_codex_review_planner_r3_conftest_guard.md`,
`_workspace/2026-11-18_codex_rereview_outbox_reconcile.md`.
**Hashe chráněných souborů porovnávej v Pythonu** (`_workspace/cache_isolation_repair_20261118/protected_sha.py`),
ne přes `rtk diff a b`: ten vrací 0 i při rozdílu.
Hotové: review po-C1 nápravy (`_workspace/2026-11-18_codex_review_post_c1_remediation.md`):
readiness a viditelnost outboxu APPROVE (kód, ne nasazení), izolace testů APPROVE.
`tests/conftest.py` chrání runtime DB při collection a běh shodí při změně kteréhokoli ze šesti
chráněných souborů nebo souboru pod `runtime/` či `src/runtime/`.
Dříve: deploy skript: review 77–81, finálně APPROVE (`_workspace/81_…`), nástroje
nainstalovány na serveru 2026-11-12; nasazení opravy svíček až po zmrazeném C1 podle
`docs/remediation/C1_FREEZE_DAY_RUNBOOK_2026-11-11.md`. Hotové: review opravy svíček (Claude,
APPROVE kód, BLOCKED nasazení) → `_workspace/77_independent_candle_refresh_review.md`; review
allowlistu (Codex) → `_workspace/77_codex_deploy_allowlist_review.md`, opraveno v `e39a1b7`.
Nasazení až po zmrazeném C1.
Producer původu C1 je po review 70, 71, 73 a 75 (APPROVE) nasazen
(`_workspace/76_c1_provenance_deploy_20261111.md`).
Od 2026-11-10 implementaci dělá Claude, Codex dostává jen zadání na audit nebo radu.
Aktuální stav a autorita: `docs/OPERATING_STATE.md`.
Podkladová data: `docs/codex_prompts/evidence/` (soubory jsou jen ke čtení).

Hotová zadání (nezpracovávat znovu):
- `CODEX_STRATEGY_LEARNING_TASKS_2026-10-02.md` → `_workspace/50_codex_strategy_learning_report.md`.
- `CODEX_LEARNING_EXPERIMENT_EVAL_2026-10-26.md` → `_workspace/57_codex_learning_experiment_eval.md`.
- `EXTERNAL_AUDIT_LEARNING_PROCESS_2026-11-09.md` → `_workspace/59_external_audit_learning_process.md`
  (nálezy zapracovány, viz `docs/OPERATING_STATE.md` a `_workspace/60_audit_remediation.md`).
- `CODEX_CANDLE_REFRESH_PHASE_FIX_2026-11-09.md` → `_workspace/63_codex_candle_refresh_fix.md`
  (lokální oprava za příznakem, výchozí vypnuto; nasazení až po C1 a review).
- `CODEX_NEW_SIGNAL_SOURCE_SCREEN_2026-11-09.md` → `_workspace/64_codex_new_signal_source_screen.md`
  (všech 7 hypotéz NO_EDGE, shrnutí `RESEARCH_FUTURES_FLOW_FINDINGS.md`; HOLDOUT je spotřebovaný,
  znovu nevyhodnocovat).
- `CODEX_POST_C1_COST_AND_LEARNING_REVIEW_2026-11-10.md` → `_workspace/65_codex_cost_and_learning_review.md`
  (fázi A provedl Claude; fáze B/C až po zmrazeném C1).

Offline vyhodnocení experimentu nad novým exportem:
`python -B scripts/research/p0_8_plus_epoch_report.py --json <export.json> --out <adresář>`

## Stav repozitáře, který je potřeba znát

- Pracovní strom je záměrně „dirty“ (stovky změněných a nesledovaných souborů).
  Nic z toho nevracej, neuklízej a necommituj.
- Produkční server neběží žádný commit z gitu: kód tam byl nasazen souborovými
  manifesty. Lokální pracovní strom je zdroj těchto manifestů.
- Bot je dlouhodobě ztrátový a nemá prokázaný edge. Nepředpokládej opak a
  netvrď ho v reportech.
- Hodně modulů s „learning“/„strategy“ v názvu není na živé cestě. Než o modulu
  řekneš, že je živý, ověř dosažitelnost z `start.py` → `bot2/main.py`.

## Živá cesta (zkráceně)

```
start.py → bot2/main.py
  market_stream.py → src/core/event_bus.py → live_quote_cache_v1 / candle_cache_v1
  p0_8_plus_shadow_evaluator.evaluate_symbol()        (jediný scheduler, PAPER_UNIFIED_ENGINE_ENABLED)
    → candle_cache_v1 (dokončené svíčky) → regime_classifier_v1
    → strategy_*_v1.generate_candidates()             (profily *_v1, *_closed_v2, *_paper_probe_v2)
    → signal_router.evaluate_signal_for_paper_entry()
        cost_model → P0 gate → evidence_budget (stop pravidlo, příznak)
        → paper_source_learning (adaptivní výběr; volitelně paper_neural_context pro BTC)
        → paper_learning_budget (frekvenční rozpočet průzkumu) → risk guard
  p0_8_plus_live_pipeline.run_live_tick() → paper_trade_executor.open_paper_position()
  paper_trade_executor.update_paper_positions() / close_paper_position()
    → paper_close_journal (durable) → local_persistent_cache.save_closed_trade()  (SQLite closed_trades)
    → v5_legacy_bridge (outbox, quota, Firebase)
  Stonkfly (src/services/stonkfly/): jen shadow / kontext, nikdy neotevírá pozice.
```

Všechny zdroje jsou v `src/services/`, pokud není uvedeno jinak. Mechanismy a
konfigurace jsou popsané v `src/services/LOGIC.md` a `docs/remediation/`
(nejnovější soubory mají přednost před staršími).

## Příkazy

- Testy: `python -m pytest -q -p no:cacheprovider <soubory>`
  (Python 3.14 lokálně, 3.12 na serveru — nepoužívej syntaxi novější než 3.12).
- Spouštěj jen cílené testovací soubory uvedené v zadání. Celá sada `tests/`
  obsahuje staré selhávající testy a některé sahají na lokální runtime soubory.
- Syntaxe bez zápisu bytecode: `python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" soubor.py`
- Lint (pokud je dostupný): `ruff check <soubory>`.

## Runtime data — nikdy neměnit

```
local_learning_storage/**        (cache.sqlite, performance_epoch.json, …)
data/paper_open_positions.json
server_local_backups/**
runtime/**, src/runtime/**
```

- Testy pracují výhradně v `tmp_path`.
- `src/services/local_persistent_cache.py` má relativní `LOCAL_DB_PATH` a při
  importu inicializuje DB. V testech cestu přesměruj přes `monkeypatch` dřív,
  než dojde k zápisu.
- Před během testů a po něm porovnej SHA-256 těchto souborů (pokud existují):
  `local_learning_storage/cache.sqlite`, `data/paper_open_positions.json`,
  `server_local_backups/paper_adaptive_learning_state.json`,
  `server_local_backups/learning_state_phase1.json`,
  `runtime/v5_quota_usage.sqlite`, `src/runtime/v5_quota_usage.sqlite`.
  Rozdíl = incident: zastav práci a nahlas ho.

## Nikdy

- `git commit`, `git push`, `git reset`, `git checkout --`, `git stash`,
  `git clean`. Změny zůstávají v pracovním stromu k review.
- SSH na server, deploy, restart služeb, spouštění GitHub workflow.
- Změna `TRADING_MODE`, `ENABLE_REAL_ORDERS`, `LIVE_TRADING_CONFIRMED` nebo
  čehokoli v cestě reálných objednávek (`execution_engine.py`, `runtime_mode.py`).
- Nové závislosti, Gunicorn/WSGI wrapper pro dashboard, nová služba nebo daemon.
- Nová obchodní větev, nová strategie nebo změna prahů bez výslovného zadání.
- Mazání, přesouvání nebo „úklid“ souborů mimo rozsah zadání.
- Tvrzení o ziskovosti. Zelené testy nejsou důkaz edge.

## Styl

- Malé moduly s jednou odpovědností, bezstavové kde to jde.
- Signalizace mezi komponentami přes `src/core/event_bus.py`.
- `logging` místo `print`; logovací značky ve tvaru `[VELKA_PISMENA]`.
- Nová rozhodovací logika: čistý modul bez I/O + injekce do volajícího
  (vzor: `p0_segment_ev_gate.py`, `risk_guard_fn` v `signal_router.py`).
- Fail-closed: chybějící nebo neplatná data znamenají zamítnutí, ne výchozí povolení.
- Nové chování za env příznakem s výchozím „vypnuto“; kód a zapnutí jsou dva kroky.
- Komentář jen tam, kde vysvětluje omezení, které z kódu není vidět.
- Složitější logiku zapiš do `src/services/LOGIC.md`.

## Jak pracovat

1. Nejdřív důkaz, potom změna: ověř nález čtením kódu (`soubor:řádek`) nebo daty.
2. Minimální diff: měň jen příčinu, žádný souběžný refaktoring.
3. Ke každé změně chování test, který bez ní selže (ověř mutací).
4. V reportu odděl ověřené od předpokládaného; `NOT_RUN` a `NOT_VERIFIED` jsou
   platné stavy.

## Kde hledat kontext

- `CLAUDE.md` — projektová pravidla a historie.
- `RESEARCH_PIVOT_CHARTER.md`, `RESEARCH_COSTWALL_FINDINGS.md`,
  `RESEARCH_LONGHORIZON_FINDINGS.md`, `RESEARCH_M5_COST_ARITHMETIC.md` —
  co už bylo otestováno a vyvráceno.
- `docs/remediation/` — stav po zářijovém auditu a nasazení.
- `_workspace/` — forenzní zápisy a reporty z jednotlivých kol.
