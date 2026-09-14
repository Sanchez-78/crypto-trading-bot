# CLAUDE — WR >50 single-path implementation, Phase 0–2/5/6 report (2026-09-14)

## Terminální stav

| Rozměr | Stav |
|---|---|
| Cíl `WR > 50 %` (paper, čistý post-fix kohort) | **`NOT_ACHIEVED`** |
| Engineering (Fáze 0–2, 5, 6 částečně) | **`PARTIAL`** |
| Release gate | **`NOT_READY_FOR_DEPLOYMENT`** |
| Live host identity / runtime content | **`NOT_VERIFIED`** (v této relaci žádné SSH) |
| REAL trading | `ABSOLUTE NO-GO` — nedotčeno |

Žádný hybridní status. Cíl WR >50 **nebyl** dosažen a v tomto běhu ani nemohl
být: neexistuje čerstvý post-fix kohort (viz Fáze 0).

---

## Fáze 0 — baseline a evidence (HOTOVO, s nálezy, které mění premisu)

Read-only agregace `local_learning_storage/cache.sqlite` (`mode=ro`, 472 řádků).

### F0-A: lokální DB je 39,8 dne stará

Nejnovější reálný close je `2026-08-05 11:06 UTC`; „teď“ je `2026-09-14`.
Tento snapshot **není live kohort** a nemůže potvrdit ani vyvrátit WR >50
pro současný kód.

### F0-B: DB obsahuje syntetickou testovací kontaminaci (116/472 = 24,6 %)

| Třída | n | Poznámka |
|---|---|---|
| `exit_ts < 2001` (fake clock, 1970-01-01) | 76 | testovací fixtures |
| `exit_reason` ∈ {`TEST`,`MANUAL`} | 35 | **všechny `win=1`** |
| `symbol` = `SYM0/SYM1/SYM2` | 3 | syntetické symboly |
| **union** | **116** | |

Testovací zápisy skončily ve stejné DB, kterou čte dashboard a všechny
dosavadní WR analýzy. `TEST`/`MANUAL` řádky jsou 100 % wins → **nadhodnocují WR**.

### F0-C: dosavadní „recent-100“ okno je 34minutový výsek

Okno `recent-100` použité v `WR_TARGET_ANALYSIS_2026-09-14.md` pokrývá
`2026-08-05 10:32 .. 11:06 UTC` = **2 058 s (34,3 min)** a samo obsahuje
6 syntetických řádků (3 `TEST` + 3 `MANUAL`, všechny wins).

**Důsledek:** dřívější závěr „rde_take 75 % vs. training_sampler 30 %,
agregovaně 48 %“ je čten z 34minutového výseku 40 dní staré, kontaminované DB.
Rozdíl mezi zdroji je reálný a na čistém kohortu ještě výraznější (níže), ale
ta konkrétní čísla nejsou platný kohort.

### F0-D: baseline s denominatorem a intervalem nejistoty

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

### F0-E: `TIMEOUT_NO_PRICE` — dva denominatory si odporují

106 řádků (22,5 % celé DB) má **`exit_price = 0.0`, `pnl_pct = 0.0`, `win = 0`**
— bez výjimky. Jde o pozice uzavřené, aniž kdy byla získána tržní cena.

Obchodní kód je sám považuje za **ne-obchody**:
`paper_trade_executor.py` jim nastavuje `learning_skipped=True`, přeskakuje
`record_close()`, a `paper_close_pipeline.canonical_learning_eligibility()`
je odmítá s explicitním důvodem `timeout_no_price_invalid`.

Dashboard (`dashboard_web.py:_rolling_window_metrics`) ale tytéž řádky čte z
`closed_trades` a každý z nich účtuje jako **PROHRU** (`pnl_pct = 0.0` není
`> 0`). **Dva denominatory v jednom systému se neshodnou na tom, co je obchod.**

### F0-F: chybějící Phase-2 attribution sloupce

Ve schématu `closed_trades` **zcela chybí**: `code_version`, `config_version`,
`segment_key`, `admission_route`, `admission_reason`, `effective_hold_s`.
Dále `bucket` je NULL u 204/472 a `tp_sl_profile` = `"unknown"` u 459/472.

---

## Fáze 1 — production-linked RED testy (HOTOVO pro rozsah Fáze 2)

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

## Fáze 2 — canonical admission (JÁDRO HOTOVO, persistence PARTIAL)

### Inventura call-siteů (Fáze 0 bod 1)

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

### Zavedený kontrakt

`paper_trade_executor.canonical_admit(*, signal, price, ts, route, reason, extra)`
— keyword-only, vrací výsledek choke plus normalizované `outcome` ∈
{`OPENED`, `BLOCKED`}. Wrapper **neobsahuje žádnou admission logiku**:
razítkuje attribution, deleguje verbatim na `open_paper_position()` a
normalizuje výsledek. Nemůže admission přerozhodnout, obejít ani opakovat.

- `effective_hold_s` **znovupoužívá** existující `_effective_paper_hold_s()`
  — nezavádí druhé pravidlo pro hold (požadavek „jeden `effective_hold_s`“).
- Neznámá verze zůstává `"UNKNOWN"`, nikdy se nedopočítává odhadem
  (Fáze 2 pravidlo 4). `segment_key` se nefabrikuje.
- Nerozpoznaný návrat choke je fail-closed → `BLOCKED`.

### Co v Fázi 2 HOTOVO NENÍ

Attribution se nyní **předává** do `open_paper_position()`, ale
**nepersistuje se do `closed_trades`** — sloupce ve schématu neexistují (F0-F).
Dokud nebude provedena schema migrace, Fáze 2 bod 2 zůstává `PARTIAL`.

---

## Fáze 5 — dashboard denominator (PARTIAL, nenasazeno)

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

## Fáze 6 — mutation-kill (PARTIAL: 3 mutanti, ne plná matice)

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

## Testy — přesné příkazy a výsledky

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

### Pre-existing selhání (NEzpůsobená touto relací)

| Test | Příčina | Důkaz, že je pre-existing |
|---|---|---|
| `test_f8b_integration.py::test_tick_hook_before_blacklist_gate_and_gated` | hledá substring v `signal_generator.py` | `signal_generator.py` není v `git status` ani touto relací měněn |
| `test_sec_01_dashboard_boundary.py::test_spa_handler_only_serves_fixed_index` | `bytes` vs `str` TypeError | netýká se metrik; soubor je necommitovaná práce dřívější relace |
| `test_observe_gate_choke.py` (5), `test_learning_hook_evidence_collection.py` (4) | `paper_state_not_ready` / `UNINITIALIZED` | `git show HEAD:...paper_trade_executor.py \| grep paper_state_not_ready` → **žádná shoda**; READY guard je necommitovaná práce dřívější relace |

### Selhání, která tato relace ZPŮSOBILA a OPRAVILA

`test_f8b_integration.py` — 2 nodes lokalizovaly „the real open call site“
podle jména `open_paper_position(\n`; přejmenováním se posunul na
`canonical_admit(\n`. Testy aktualizovány na nové jméno, **sémantika
assertions zachována** (ordering `record < ret < open_call` beze změny).

---

## Změněné soubory a ownership caveat

Commit `2d68876` na větvi **`wr50/canonical-single-path-phase2`** (lokální,
**nepushnuto**), 9 souborů, +923/−124.

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
kopírovány, hashovány ani maž ány.

---

## Release gate (Fáze 7)

```text
python tools/release_gate.py --json
-> ready=false
   reasons = [protected_paths_dirty,
              immutable_artifact_not_created,
              paper_smoke_evidence_not_attached]
```

Stav **nezměněn** touto relací. SHA-256 protected paths po změnách:

| Soubor | SHA-256 (prefix) |
|---|---|
| `src/services/paper_trade_executor.py` | `cb344b4d4bdac9e6…` |
| `src/services/dashboard_web.py` | `636b532b779abbd0…` |
| `src/services/realtime_decision_engine.py` | `94d730681529e550…` |
| `src/services/trade_executor.py` | `dec895b4be1b619f…` |
| `systemd/cryptomaster-dashboard.service` | `cbe5646796b15281…` (nezměněno) |

Gate nebyl obcházen. `NOT_READY_FOR_DEPLOYMENT` trvá.

---

## Počty (tato relace)

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

## Reziduální rizika

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

## Přesný další krok

**Fáze 3 na `TIMEOUT_NO_PRICE`**, v tomto pořadí:

1. Production-linked RED test: pozice, které vyprší bez čerstvé ceny, nesmí
   být zapsány jako `win=0` s `exit_price=0.0` — buď se získá reálná cena,
   nebo se pozice karantenizuje **mimo** `closed_trades`.
2. Teprve poté schema migrace `closed_trades` o šest chybějících Phase-2
   sloupců, aby `canonical_admit()` attribution skutečně persistovala.
3. Teprve s (1) a (2) živě běžícími začít Fázi 4 shadow kohortu s předem
   zafixovaným `code_version`/`config_version`, minimální velikostí vzorku a
   holdout oknem — to je jediná cesta, jak lze WR >50 legitimně tvrdit.

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.
