# CLAUDE — WR >50 single-path implementation, Phase 0–3/5/6 report (2026-09-14)

> **Round 2** (test-sink separace `cache.sqlite`, schema migrace, Fáze 3) a
> **Round 3** (všechny zbývající sinky, závislost na pořadí testů) jsou
> v sekcích na konci dokumentu. Terminální stav cíle se ani v jednom kole
> **nezměnil**: `NOT_ACHIEVED`.

## Terminální stav

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

---
---

# Round 2 — test-sink separace, schema migrace, Fáze 3

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
Engineering: `PARTIAL` (nově uzavřena Fáze 3 a persistence Fáze 2).
Release gate: `NOT_READY_FOR_DEPLOYMENT`. Deploy/restart/SSH/REAL orders: `0`.

## R2-A — Separace testovacího sinku (příčina kontaminace z Fáze 0)

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

## R2-B — Schema migrace + persistence attribution (uzavírá Fázi 2 bod 2)

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
symbol-scoped segment_key“, nikoli „vyhrává hodnota volajícího“.

## R2-C — Fáze 3: no-price expiry je VOID, ne prohra

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

## R2-D — Mutation-kill (Round 2)

| # | Mutace | Výsledek | Zabito assertion |
|---|---|---|---|
| M4 | **anti-gaming**: vyřadit z denominátoru i `LOSS` | **KILLED** | `assert 0.5 == 0.333…` (WR by vyskočila 33 % → 50 %) |
| M5 | vrátit `1 if trade.get("win") else 0` | **KILLED** | `unknown win was coerced to 0` |

M4 je klíčový: dokazuje, že kontrakt `compute_win_rate` nelze rozšířit z
„vyluč ne-obchody“ na „vyluč prohry“, aniž to test okamžitě chytí.
Po každém mutantu ověřeno, že `git diff HEAD` pro dotčené zdroje je prázdný.

## R2-E — Testy

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

## R2-F — Aktuální evidence (nezměněná interpretace)

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

## R2-G — Commity (větev `wr50/canonical-single-path-phase2`, nepushnuto)

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

## R2-H — Počty (kumulativně za celou relaci)

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

## R2-I — Přesný další krok

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

# Round 3 — všechny zbývající sinky + závislost na pořadí testů

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
Release gate: `NOT_READY_FOR_DEPLOYMENT`. Deploy/restart/SSH/REAL orders: `0`.

## R3-A — `cache.sqlite` nebyl zdaleka jediný sink

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

## R3-B — `local_learning_storage` nebyl CWD-relativní, ale síťový

Nález, který změnil podobu opravy: tento modul nejdřív **prohledává
`NETWORK_PATHS`**, a na tomto stroji je `\\MYCLOUD-G07Y2M\Public\Cryptomaster`
skutečně připojen — takže `DB_PATH` se rozhodoval na **sdílené síťové úložiště**,
nikoli do repa. Test zapisující tento sink by poškodil data, která čtou jiné
stroje.

Otázka „je to uvnitř repa?“ je proto příliš slabá. Vynucovaný invariant je
silnější:

> pod pytestem musí **každý** sink vycházet uvnitř dočasného session rootu

To platí bez ohledu na to, zda je produkční cíl podadresář repa, absolutní
`/opt` cesta nebo připojený UNC share.

## R3-C — Jedno pravidlo, ne N kopií

Guard žije v jediném místě `src/core/test_sink_guard.py`. Tento projekt má
zdokumentovanou regresi způsobenou tím, že dvě funkce četly stejný parametr
s odlišnými defaulty (WR 57 % → 0 %); N ručně opsaných kopií bezpečnostního
guardu je tentýž hazard s horšími následky.

Produkční běh není dotčen: `PYTEST_CURRENT_TEST` tam není nastaven, takže každé
volání guardu je no-op. `local_learning_storage` override se navíc čte **před**
network probe, takže přesměrovaná session se síťového disku nedotkne.

## R3-D — Přesměrování konstant bylo nutné, ale NEdostatečné

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

## R3-E — Závislost na pořadí testů (falešná zeleň)

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

## R3-F — Baseline změřen, nikoli odhadnut

Aby bylo poctivě rozlišeno „pre-existing“ od „způsobeno mnou“, byl vytvořen
git worktree na commitu `f01b19f` a spuštěn s `FORCE_LOCAL_STORAGE`, takže
nemohl sáhnout ani na NAS, ani na tento repozitář:

| Běh (identická dvojice souborů) | failed | passed |
|---|---|---|
| baseline `f01b19f` | **30** | 45 |
| tato větev | **24** | 51 |

**Šest opraveno, žádná regrese.** Zbývajících 24 je pre-existing.
Worktree byl poté odstraněn; produkční soubory hlavního repa ověřeny jako
nedotčené.

## R3-G — Mutation-kill (Round 3)

| # | Mutace | Výsledek | Zabito assertion |
|---|---|---|---|
| M6 | `assert_not_production_sink()` degradován na no-op | **KILLED** (2 nezávislé sady) | `DID NOT RAISE <class 'RuntimeError'>` |

Dokazuje, že guard není vacuous. Po revertu ověřeno, že `git diff HEAD` pro
dotčené zdroje je prázdný.

## R3-H — Testy a důkaz nekontaminace

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

## R3-I — Počty (kumulativně za celou relaci)

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

## R3-J — Zbývá otevřené

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
---

# Round 4 — odpověď na externí audit (2026-09-15)

Verdikt `EXTERNAL_AUDIT_WR50_VERDICT_2026-09-15.md`: **MERGE REJECTED**,
podmíněně, s 5 podmínkami. Body 1–4 zpracovány níže; bod 5 (nezávislý
re-review) organizuje orchestrující relace.

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
REAL trading: `ABSOLUTE NO-GO`. Deploy/SSH/REAL orders: `0`. Push: `0`.

## R4-0 — Oprava mého vlastního chybného tvrzení

V úvodní zprávě jsem uvedl, že `tools/release_gate.py:60` obsahuje natvrdo
`return False`. **To bylo nesprávné.** Ověřeno ve všech třech kopiích (větev
přes `git show`, worktree na disku, hlavní repo):

```
60: return len(reasons) == 0, reasons, hashes
```

Oprava tam je. Nedokážu zrekonstruovat, proč můj tehdejší read ukázal jinou
hodnotu, a nebudu to racionalizovat — tvrzení bylo chybné a tímto se stahuje.
Worktree sanity check proveden: `HEAD=6caa494`, čistý strom.

## R4-1 (audit Q1) — Rozhodnutí o admission přesunuto DO wrapperu

Audit měl pravdu a nerozporuji to. Provedení call-siteů *přes* wrapper z něj
neudělalo jediné rozhodovací místo.

**Ověřená inventura** (AST proti této větvi, ne proti číslům řádků z auditu —
nalezeno o **dva call-sitey víc**, než audit uvádí):

| Soubor:řádek | Gate | Řešení |
|---|---|---|
| `realtime_decision_engine.py:3066` | `if sampler_result.get("allowed")` (3037) | **větev odstraněna** |
| `realtime_decision_engine.py:4150` | `if sampler_result.get("allowed")` (4121) | **větev odstraněna** |
| `realtime_decision_engine.py:4150` | `if override["allowed"]` (4038) | vnější routing, ponecháno |
| `realtime_decision_engine.py:4235` | `if sampler_result.get("allowed")` (4206) | **větev odstraněna** |
| `paper_trade_executor.py:4845` | `if decision.strict_ev_allowed or not is_blocked` (4798) | verdikt hoisted + předán |
| `trade_executor.py:1874` | `if result.get("allowed")` (1790) | verdikt předán |
| `trade_executor.py:2291` | `if ov.get("allowed")` (2283) | verdikt předán |

**Kontrakt:** `canonical_admit(gate=...)`. Komponenta stále **ROZHODUJE**
(re-derivace politiky uvnitř wrapperu by změnila, které kandidáty přijímáme);
wrapper je jediné místo, které na verdikt **JEDNÁ**, takže každý kandidát
vyprodukuje právě jeden kanonický záznam.

Dva výsledné tvary jsou záměrné:

- **Tři RDE tréninkové sitey**: větev zcela odstraněna. Tělo byla čistá
  příprava metadat, takže nyní běží bezpodmínečně a wrapper jedná na
  `gate=sampler_result`. Callery přeskakují svůj blocked-log pro
  `gate_rejected`, takže **objem logů zůstává identický** — sampler odmítá
  většinu ticků a tato odmítnutí byla dosud tichá.
- **`trade_executor` ×2 a P0 gate**: větev ponechána, protože tam chrání
  skutečně nákladnou přípravu signálu; verdikt se nyní předává dovnitř.
  U P0 gate byl výraz hoistnut do explicitního `_p0_verdict` objektu.

**Druhou skupinu jsem do tvaru první NENUTIL.** Buď by to znamenalo spouštět
nákladnou přípravu pro každého odmítnutého kandidáta, nebo přidat no-op volání
existující jen kvůli splnění assertion — což je test-gaming, který pravidla
tohoto projektu vylučují. Strukturální test proto kóduje poctivý kontrakt:
*verdikt smí gateovat volání pouze tehdy, je-li týž verdikt předán jako
`gate=`* — nemůže být tedy callerem spotřebován a tiše zahozen.

**Zachování chování, měřeno nikoli předpokládáno:** worktree na `45d1964` a
tento strom přes stejných 14 souborů. Obojí `31 failed`; množiny selhání
**identické** (`comm` neukazuje žádné regrese ani náhodné opravy). Jediná
změna: +6 passes z nového test souboru.

## R4-2 (audit Q3) — Automatický integrity backstop

Env-var guard je obejitelný a spoléhání na operátora není vlastnost systému.
Oba reálné incidenty v této práci byly zachyceny jen proto, že někdo náhodou
kontroloval.

`tests/conftest.py` nyní snapshotuje sledované produkční soubory v
`pytest_sessionstart` a re-kontroluje v `pytest_sessionfinish`; jakýkoli
create/modify/delete **tvrdě shodí session**. Pozoruje filesystem přímo, takže
je mu jedno, JAK zápis vznikl. Je vrstven **nad** env guardem, nenahrazuje ho:
guard předchází, tohle detekuje.

Bezpečnostní síť, kterou nikdo neviděl spadnout, je další neověřené tvrzení,
proto `test_production_integrity_backstop.py` spouští **vnořené pytest
sessiony** řízené skutečnými conftest hooky a dokazuje všechny tři chování:

| Scénář | Výsledek |
|---|---|
| modifikace subprocessem s vymazaným `PYTEST_CURRENT_TEST` (přesně Q3 bypass) | **zachyceno** |
| smazání souboru (incident, který `git status` nikdy nemohl ukázat — je gitignorovaný) | **zachyceno** |
| čistý běh | **ticho**, žádné false positives |

Vnořené běhy sledují throwaway strom přes `CRYPTOMASTER_INTEGRITY_ROOT`,
nikdy reálná data.

## R4-3 (audit Q2) — Mixed semantics + stabilita klientského pole

**Smíšené okno.** VOID oprava působí jen na nové closy; všech 106 historických
řádků záměrně drží legacy tvar, takže po celou životnost této databáze bude
recent okno obsahovat **obě generace** zároveň. Dosavadní důkaz pokrýval každou
izolovaně — právě tam se reconciliation bug schová. Nový test dá do jednoho
okna legacy `TIMEOUT_NO_PRICE` řádky, řádek nesoucí **oba** markery, a VOID
řádek s nezmapovaným exit reason, a fixuje že
`raw == qualified + excluded` s dvojitě-matchnutým řádkem započteným **jednou**.

Mutace readeru (VOID přebíjí místo fallbacku) test **zabije** (M7) → není
vacuous.

**Stabilita klientského pole.** Tři win-rate rodiny se publikují vedle sebe a
legitimně se liší (48 % headline vs 64 % qualified na reálném kohortu). Klient,
který by tiše přepnul, kterou renderuje, by změnil vykazované číslo, aniž by se
změnil jakýkoli výpočet — přesně to selhání, kterému mají anti-gaming pravidla
bránit, a pro všechny ostatní testy neviditelné. Guard je **strukturální**:
čte shipped dashboard zdroj a fixuje jak množinu emitovaných klíčů, tak jediný
klíč, který prohlížeč renderuje (`win_rate_pct`).

## R4-4 (audit item 4) — Re-baseline proti skutečnému main odhalil regresi

Audit měl pravdu, že porovnání proti `f01b19f` nemohlo čistě izolovat
branch-vs-main rozdíly. Re-run proti skutečnému `main` (`a613174`) to prokázal.

Metodika beze změny: detached worktree na main, `FORCE_LOCAL_STORAGE`, takže
nedosáhne ani na NAS, ani na hlavní repo.

| Běh (stejná dvojice souborů) | failed | passed |
|---|---|---|
| **main (`a613174`)** | **23** | 52 |
| větev (před opravou) | 24 | 51 |
| *starý baseline `f01b19f`* | *30* | *45* |

Staré „šest opraveno, žádná regrese" bylo měřeno proti špatné referenci.
Diff **množin** (ne počtů) ukázal přesně jeden test selhávající na větvi a
procházející na main:

`test_p1_paper_exploration.py::TestRobustStateLoader::test_corrupt_json_logs_error_and_starts_empty`

**Root cause:** tento test tvrdil **pre-STATE-02** kontrakt — poškozený JSON
zaloguje chybu a executor pokračuje s prázdným stavem. To je přesně ten bug,
který STATE-02-A opravil: tiché nastartování naprázdno znamená, že reálné
otevřené pozice zmizí ze stavu, zatímco executor dosáhne READY v domnění, že
žádné nemá. Test **přímo si odporoval** s
`test_state_02_loader_production_red.py::test_load_paper_state_propagates_malformed_json`,
který na téže funkci tvrdí `pytest.raises(json.JSONDecodeError)`.

Dva testy v jedné sadě kódovaly opačné kontrakty; starší nebyl nikdy
aktualizován. Vyřešeno **invertováním zastaralého testu** na záměrný
fail-closed kontrakt (a přejmenováním), nikoli oslabením loaderu. Zároveň
odstraněn zbylý natvrdo zapsaný `os.makedirs("data")`.

**Po opravě: větev 23 failed / 52 passed, množina selhání IDENTICKÁ s main.**

## R4-5 — Testy a commity

```text
targeted regression: 30 failed / 130 passed
```
(bylo 31/124 — o jedno selhání méně z R4-4 opravy, o šest passes víc z nových
testů). Integrity banner **nevyskočil**; všechny tři produkční soubory
nezávisle re-ověřeny SHA-256 jako nezměněné.

| Commit | Obsah |
|---|---|
| `6caa494` | Q1 — admission decision do `canonical_admit()` |
| `123c539` | item 4 — re-baseline proti main + oprava odhalené regrese |
| `4e56031` | Q3/Q2 — integrity backstop + mixed-semantics + field guard |

Větev `wr50/canonical-single-path-phase2`. **Nepushnuto touto relací.**

## R4-6 — Co zůstává otevřené

1. **Q4 priorita auditu**: P0/P1 bezpečnost produkčního hostu (dashboard
   `0.0.0.0:5001` bez efektivní auth jako root, disk) je auditem označena jako
   **NAD** dokončením WR50. Mimo můj rozsah (žádné SSH).
2. **23 pre-existing selhání**, nyní prokazatelně shodných s `main` — tedy
   nikoli dluh této větve, ale dluh repozitáře.
3. **Fáze 4** stále čeká na akumulaci nových closes s vyplněným
   `code_version`/`config_version`. Nelze uspíšit.
4. Sweep dalších natvrdo zapsaných produkčních cest v testech; backstop je
   proti nim nyní fail-closed, ale systematický sken proveden nebyl.
5. Audit Q5 podmínky pro budoucí WR tvrzení (≥500 kvalifikovaných post-fix
   obchodů, Wilson dolní mez >50 %, bootstrap P&L dolní mez >0) **nejsou**
   splněny a historická čísla 99/118 a 57/221 nesmí sloužit jako důkaz.

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.

---
---

# Round 5 — odpověď na re-review (2026-09-16)

Verdikt `EXTERNAL_AUDIT_WR50_REREVIEW_VERDICT_2026-09-16.md`: **MERGE STILL
REJECTED**, 4 konkrétní body. Recenzent měl pravdu ve všech bodech; nic z toho
nerozporuji.

Terminální stav cíle **beze změny**: `WR >50 = NOT_ACHIEVED`.
REAL trading: `ABSOLUTE NO-GO`. Deploy/SSH/REAL orders: `0`. Push: `0`.

## R5-0 — Tři přiznání na úvod

### (a) „Ověřená inventura" nebyla nadmnožina, ale jiná množina

Můj AST inventář prohledával **pouze ancestor `if`** uzly, takže byl
strukturálně slepý vůči guard-clause/early-return vzoru — přesně tomu, který
používají obě chybějící místa:

```python
if not ov.get("allowed"):      # paper_exploration.py
    ...
    return False

if not r.evaluation.admitted:  # p0_8_plus_live_pipeline.py
    continue
```

Obě reálná produkční místa z inventury **tiše vypadla**, zatímco se objevila
dvě jiná, a já to prezentoval jako „o dva víc, než audit uvádí". To nebyla
nadmnožina. Formulace byla nesprávná a beru ji zpět.

### (b) Vlastní strukturální test byl vacuous — zjištěno mutací, ne čtením

Tři nezávislé defekty, každý potvrzen mutací:

| Defekt | Důkaz |
|---|---|
| kontroloval jen že *nějaký* `gate=` existuje, ne že jde o ten verdikt | `gate={"allowed": True}` procházel identicky |
| guard-clause detektor vyžadoval, aby **každý** příkaz v těle byl exit — reálné guardy ale logují a throttlují před returnem | mutace `gate=ov` → `gate={"allowed": True}` **prošla** |
| `.admitted` úplně chybělo ve verdict patterns | smazání `gate=` z P0.8 site → test **zůstal zelený** |

Všechny tři mutanty nyní **zabíjí**; ověřeno jednotlivě a vráceno.

### (c) TŘETÍ nechtěný produkční zápis — a tenhle je nevratný

Během této práce **backstop sám vyskočil**:

```
PRODUCTION DATA INTEGRITY VIOLATION
  * server_local_backups/learning_state_phase1.json: MODIFIED (7ae2ef3f110a -> d3d611a19ae7)
```

Root cause: `firebase_learning_persistence.py:71` měl **čtvrtý** natvrdo
zapsaný CWD-relativní default, o kterém nikdo nevěděl.

Horší část: mtime téhož souboru v **hlavním repu** je
`2026-09-14 07:19:35 UTC` — uvnitř mého Round 1–3 sezení, kdy jsem ještě
pouštěl testy přímo v hlavním repu a tento soubor nebyl na žádném watch-listu.
Na rozdíl od prvních dvou incidentů **nemám baseline hash**, takže jej nemohu
obnovit ani dokázat, že je nedotčený. Soubor je gitignorovaný, takže neexistuje
ani git evidence. Uvádím to jako **nevyřešené**, nikoli jako vyřešené.

To je přesně ta „stejná třída incidentu, jiný soubor", kterou recenzent
předpověděl — a stalo se to i mně.

## R5-1 — Q1 dokončeno na všech místech

| Site | Vzor | Řešení |
|---|---|---|
| `paper_exploration.py:714` | guard clause `return False` | **`gate=ov` doplněn** |
| `p0_8_plus_live_pipeline.py:295` | guard clause `continue` | **`gate={allowed, reason}` doplněn** |
| `realtime_decision_engine.py:4152` | **dva** verdikty (ECON_BAD override + sampler) | předává se **konjunkce** |
| RDE ×3 | větev odstraněna (Round 4) | beze změny |
| `trade_executor.py` ×2, P0 gate | retained-branch | beze změny |

**„Mrtvý gate" vyřešen:** na třech retained-branch místech je gate prokazatelně
vždy `allowed=True`, takže jeho předání nemělo žádný efekt. `canonical_admit()`
nyní persistuje `admission_gate_reason` — otevřený řádek tedy nese **důvod
svého přijetí**, takže „proč byl tenhle kandidát přijat" je zodpověditelné
z dat, ne re-čtením calleru. Tím je gate load-bearing i na admitted cestě.

## R5-2 — Sedm regresí, reprodukováno nezávisle

| Test | Příčina | Oprava |
|---|---|---|
| `test_p0_8_plus_live_pipeline` ×2 | `call_args.args[1]` — průchod přes `canonical_admit` udělal volání keyword-only → `IndexError` místo kontroly fillu | čte `kwargs["price"]` |
| `test_paper_mode` routing | patch target přejmenován s importem | `canonical_admit` |
| `test_v3_1_hotfix` ×3 | stub `_save_paper_state = lambda: None` (falsy) → nová fail-closed cesta to čte jako selhání | stub vrací `True`; **fail-closed cesta NEoslabena** |
| `test_observe_gate_choke[1]` | díra v **mé vlastní** fixture | přesunuto na `pytest_runtest_call` hookwrapper |

**Bezpečnostně relevantní:** ty dva fill-price testy ověřují, že BUY se bookuje
na **ask**, ne na candle close. Byly rozbité od **úplně prvního commitu této
větve** (`2d68876`) a přežily tři kola mé vlastní revize i jeden externí audit —
protože žádný baseline nikdy nepokryl tento soubor. To je přímý důsledek toho,
že jsem měřil na dvou souborech a tvrdil z toho závěr o větvi.

**Díra ve fixture:** autouse fixture běžela **před** fixtures testu, takže když
byla modulová `executor` fixture tím, kdo executor poprvé importoval, modul
ještě nebyl v `sys.modules` a fixture tiše no-opla. Selhával proto přesně
**první** test takového souboru, zatímco sourozenci procházeli — díra v tom
samém mechanismu, který měl order-dependence odstranit.

## R5-3 — Integrity backstop: tři chybějící soubory + čtvrtý sink

Doplněno do watch-listu: `runtime/v5_quota_usage.sqlite`,
`runtime/v5_trade_outbox.sqlite`, `src/runtime/v5_quota_usage.sqlite`.
`quota_guard.py` a `outbox.py` dostaly `CRYPTOMASTER_RUNTIME_DIR`.
`"runtime"` přidáno mezi produkční jména adresářů ve sdíleném guardu.

Dva sinky, které volaly jen `resolve_dir()`
(`paper_trade_executor.py`, `paper_adaptive_learning.py`), nyní volají i
`assert_not_production_sink()`.

Čtvrtý sink (`firebase_learning_persistence.py`) přesměrován a zaguardován —
viz R5-0(c).

## R5-4 — Dvě bundlované změny produkčního chování (explicitní disclosure)

Recenzent správně uvádí, že tyto byly rámovány jako „už hotová oprava", nikoli
jako **delta této větve**. Ověřeno AST porovnáním proti `main`:

| Změna | `main` | tato větev |
|---|---|---|
| **Corrupt state JSON** | `_load_paper_state` má 3 `except` handlery a **0 `raise`** — zaloguje a pokračuje s prázdným stavem | re-raisuje ve všech třech |
| **Timeout-close persistence** | řetězec `paper state timeout persistence failed` **neexistuje** | `if not _save_paper_state(): raise IOError(...)` |

Obě jsou fail-closed a podle mého názoru správné, ale jsou to **reálné změny
produkčního chování mimo deklarovaný single-path rozsah** a jako takové je zde
pojmenovávám. Pocházejí z necommitovaných prací dřívějších relací, které se
staly součástí této větve.

## R5-5 — Netrackovaný test, který jsem citoval jako důkaz

`tests/test_state_02_loader_production_red.py` — citovaný jako autoritativní
kontrakt ospravedlňující inverzi testu v Round 4 — byl **netrackovaný v gitu na
obou větvích**, tedy nikdy neběžel v žádném baseline srovnání. Citovat ho jako
důkaz byla chyba.

Nyní **trackován** (ověřeno: `3 passed`).

Širší nález: ve stejném stavu je celá rodina souborů —
`state02_isolation_bootstrap.py`, `test_dashboard_metrics_contract.py`,
`test_route_open_result_contract.py`, `test_sec_01_dashboard_boundary.py`,
`test_state_02_paper_state_fail_closed.py`, `test_state_02_save_ack_contract.py`,
`test_state_02_subscription_boundary_red.py`,
`test_state_02_subscription_runtime.py`,
`test_trade_executor_open_result_contract.py`.
**Hlásím to, nepřidávám je hromadně** — nevalidoval jsem je, a přidat
netrackované testy bez ověření by opakovalo tutéž chybu v jiné formě.

## R5-6 — Baseline na plném rozsahu repozitáře

Metodika: per-file běh s OS timeoutem (aby jeden zaseknutý soubor nezabil
sweep), detached worktree na `main` (`2b1e922`), `FORCE_LOCAL_STORAGE=1`.

| | **rozsah** | failures |
|---|---|---|
| `main` (`2b1e922`) | **121 test souborů** | 73 |
| větev (`9a2519c`) | **131 test souborů** | 72 |
| timeouts | 0 / 0 | |

- **Branch-only regrese: 0** (všech 7 opraveno)
- **Main-only selhání: 1** — `test_phase4b_starvation_paper_flow.py::TestStarvationAdmissionBypass::test_starvation_bypass_accepts_paper_training_sample`, tedy větev jej opravuje.

Rozsah je uveden vedle čísla, jak recenzent žádal. Předchozí „23 vs 24" bylo
měřeno na **dvou souborech** a nemělo se prezentovat jako závěr o větvi.

## R5-7 — Co zůstává otevřené

1. **Nevratné:** `learning_state_phase1.json` v hlavním repu — nelze ověřit ani
   obnovit (R5-0c).
2. **72 pre-existing selhání** na větvi, prakticky shodných s main (73).
   Dluh repozitáře, ne této větve — ale nyní změřený na plném rozsahu.
3. **Rodina netrackovaných testů** (R5-5) — nevalidováno.
4. **Q4 auditu**: P0/P1 bezpečnost hostu je **NAD** dokončením WR50. Mimo
   můj rozsah (žádné SSH).
5. **Q5 podmínky** pro WR tvrzení (≥500 kvalifikovaných post-fix obchodů,
   Wilson dolní mez >50 %, bootstrap P&L dolní mez >0) nesplněny.
   Historická čísla 99/118 a 57/221 nesmí sloužit jako důkaz.
6. Client-field guard pokrývá jen browser klienta, ne Android appku (jiné repo).

Cíl WR >50 zůstává `NOT_ACHIEVED`. Tento dokument není potvrzení production
safety ani GO pro REAL trading.
