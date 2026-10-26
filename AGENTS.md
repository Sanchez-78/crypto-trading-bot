# AGENTS.md — pravidla pro Codex a další kódovací agenty

Projekt: **CryptoMaster** — papírový (PAPER) obchodní bot pro krypto, Python.
Komunikace s uživatelem a reporty: **česky**. Identifikátory a kód: anglicky.

## Aktuální zadání

Žádné otevřené zadání. Čekej na nové zadání od operátora.
Podkladová data: `docs/codex_prompts/evidence/` (soubory jsou jen ke čtení).

Hotová zadání (nezpracovávat znovu):
- `CODEX_STRATEGY_LEARNING_TASKS_2026-10-02.md` → `_workspace/50_codex_strategy_learning_report.md`.
- `CODEX_LEARNING_EXPERIMENT_EVAL_2026-10-26.md` → `_workspace/57_codex_learning_experiment_eval.md`.

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
