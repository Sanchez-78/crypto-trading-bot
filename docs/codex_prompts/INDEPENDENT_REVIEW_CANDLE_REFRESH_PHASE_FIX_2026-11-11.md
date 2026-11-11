# Nezávislé review opravy obnovování dokončených svíček

**Role:** reviewer, který neimplementoval opravu z 9. 11. 2026. Implementaci dělal Codex (`_workspace/63_codex_candle_refresh_fix.md`), proto ji tentýž autor nesmí vydávat za nezávislé review. Reviewer jen ověřuje a radí.

**Výstup:** `_workspace/77_independent_candle_refresh_review.md` (česky), syntetické důkazy pod `_workspace/candle_refresh_review_20261111/`. Uveď zvlášť verdikt ke kódu (`APPROVE` / `CHANGES_REQUIRED`) a připravenost nasazení (`READY` / `BLOCKED`).

**Hranice:** dokud C1 není zmrazené a jeho původ ověřený, žádné SSH, deploy, restart bota, změna konfigurace, commit/push ani čtení výsledků obchodů po cutoffu. Neměň C1 cutoff, kontrolní podíl, limity, obchodní parametry ani běžící proces. V tomto review neměň zdrojový kód nebo testy; pro mutace použij pouze izolovanou kopii.

## Podklady a přesný rozsah

- Zadání a původní důkazy: `docs/codex_prompts/CODEX_CANDLE_REFRESH_PHASE_FIX_2026-11-09.md`, `_workspace/63_codex_candle_refresh_fix.md`, `_workspace/candle_refresh_20261109/task.diff`, `before.json`, `after.json` a uložené preimage soubory.
- Šest změněných souborů: `src/services/candle_cache_v1.py`, `src/services/p0_8_plus_live_pipeline.py`, `src/services/LOGIC.md`, `tests/test_completed_candle_cache.py`, `tests/test_completed_strategy_pipeline.py`, `tests/test_p0_8_plus_live_pipeline.py`.
- Výchozí stav je dirty pracovní strom, nikoli samotný Git HEAD. Před review znovu spočítej SHA-256 těchto šesti souborů proti `after.json`; při driftu zaznamenej rozdíl a nepovažuj starý `task.diff` za přesný. Před/po testech porovnej SHA šesti chráněných runtime souborů z `AGENTS.md`.

## Otázky, na které musí review odpovědět

1. Potvrď příčinu ztracených kandidátů z živé cesty `start.py → bot2/main.py → p0_8_plus_live_pipeline → p0_8_plus_shadow_evaluator → candle_cache_v1 → signal_router`: minutová fáze plánovače, jitter symbolů, `last_attempt`, čas poslední dokončené svíčky a veto při stáří nad 90 s. Rozlišuj vlastní reprodukci od serverových čísel převzatých z `_workspace/62_stale_market_data_rejections_since_restart.md`.
2. V zapnutém režimu ověř obnovu při změně UTC minuty i po 59,x s a při BTC probuzení, přitom nejvýš jeden běžný REST pokus na symbol/minutu. Výslovný `force_refresh` je zvláštní existující výjimka. Ověř prodlevu po chybě `max(60, refresh_seconds)`, včetně výjimky, prázdné odpovědi, `None`, rollbacku hodin a `refresh_seconds=600`.
3. Ověř, že partial candle se nepovýší na completed jen plynutím času nebo při requestu přes hranici minuty; cutoff používá začátek úspěšného fetch. Testuj oddělení cutoffů po symbolech, sdílenou cache pro legacy čtenáře a chování při souběhu pravidelného ticku a BTC wake.
4. Ověř bezpečný default příznaku `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED=false`, jeho čtení při konstrukci cache, neměnný limit 90 s, generátory, router, P0/risk/executor, TP/SL, náklady, CONTROL podíl a žádnou cestu k REAL. Zkontroluj, že `data_age_ms` v logu odpovídá přesně hodnotě použité při rozhodnutí a nezmění admission.
5. Ověř nasaditelnost. **Doplněno 2026-11-11 (Claude):** rozšíření allowlistu je připravené
   v posledním commitu měnícím `deploy/research_eval/deploy_bot_files.sh` (ALLOWED_FILES +
   `candle_cache_v1.py`, `p0_8_plus_live_pipeline.py`; ALLOWED_KEYS +
   `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED`; validátor přijme pro příznak jen
   `true`/`false`) a statický test `tests/test_deploy_bot_files_allowlist.py`. Reviewuj
   tento diff jako součást nasazení: nerozšiřuje cesty k nákladům, TP/SL, executoru ani REAL?
   Stačí `py_compile` a kontrola journalu po restartu, nebo je nutný import obou modulů ve
   staging validaci? Platí postup rollbacku i pro dva nové soubory? Server má zatím starou
   verzi skriptu (SHA `52d50fe7…`), nová se nasadí až po tomto review. Skript ani opravu v
   tomto review neměň. Spusť navíc `tests/test_deploy_bot_files_allowlist.py`.
6. Posuď dopad na populaci kandidátů. Nová kohorta po zapnutí musí mít vlastní `cohort_start_ms`, verzi cache/kódu a cost model; nesmí se sloučit s C1. Více kandidátů ani lepší P/L po zapnutí nejsou důkaz účinku učení.

## Ověření

Spusť jen cílené testy `tests/test_completed_candle_cache.py`, `tests/test_candle_cache_v1.py`, `tests/test_completed_strategy_pipeline.py`, `tests/test_p0_8_plus_live_pipeline.py` a `tests/test_neural_scheduler.py`, nejlépe přes existující `_workspace/code_audit_20260921_runner.py` (code-only snapshot bez runtime DB). Potvrď přinejmenším syntetickou fázi `:47`, jitter mezi symboly, stale veto a negativní test proti partial candle. V izolované kopii ověř, že návrat staré obnovy rozbije specifické nové testy; nepřepisuj pracovní strom. Ověř AST s gramatikou Pythonu 3.12, diff a hashe chráněných runtime souborů.

Report musí uvést přesné `soubor:řádek`, testy PASS/FAIL/SKIP, vlastní reprodukce, zděděná tvrzení, neověřené serverové vlastnosti a konkrétní blocker nasazení. I při schválení kódu platí: aktivace až po ověřeném zmrazení C1, s oddělenou kohortou a bezpečným rollbackem.
