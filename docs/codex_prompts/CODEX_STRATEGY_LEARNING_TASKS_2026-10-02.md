# Codex zadání: strategie a učení — měření, stop pravidlo, kalibrace (2026-10-02)

> **STAV: DOKONČENO 2026-10-07** — report `_workspace/50_codex_strategy_learning_report.md`.
> Nezpracovávat znovu. Aktuální zadání je v `AGENTS.md`.

**Pro:** Codex (analýza + implementace). **Review:** Claude / operátor.
**Repozitář:** `C:\Projects\CryptoMaster_srv`, větev `main`. Pracovní strom je záměrně
„dirty“ (asi 400 změněných/nesledovaných položek) — to je výchozí stav, ne chyba.
**Režim:** pouze PAPER. Žádný deploy, žádný push, žádný přístup na server.

Obecná pravidla repozitáře jsou v `AGENTS.md` v kořeni. Tento dokument je
samostatný: nepředpokládá znalost předchozí konverzace.

Postup: **Fáze A** (ověř si fakta sám, nic neměň) → **Fáze B** (čtyři úkoly) →
**Fáze C** (závěrečný report).

---

## 1. Ověřený stav (server, read-only dotaz 2026-10-02)

Podkladová data jsou v repu:
`docs/codex_prompts/evidence/epoch_20260925_closed_trades.json` — všech 82
uzavřených obchodů aktuální epochy (epocha `629c052e…`, začátek
`1790316112.19` = 2026-09-25 06:01:52 UTC). Jednotky: `pnl_pct` je procento
z notionalu po modelovaných nákladech, **bps = `pnl_pct × 100`**.

Všechny obchody epochy otevřela pipeline P0.8+
(`src/services/p0_8_plus_live_pipeline.py`), bucket
`P0_8_PLUS_EVIDENCE_COLLECTION`, vše v režimu `SIDEWAYS`, symboly ADA/SOL/ETH.
Původní cesta `signal_generator.py` → `realtime_decision_engine.py` neotevřela
v epoše žádný obchod.

| `learning_source` | n | průměr (bps) | sd (bps) | horní 95% mez | dolní 95% mez |
|---|---:|---:|---:|---:|---:|
| `sideways_mean_reversion_v1` | 57 | −11,80 | 28,28 | **−5,64** | −17,96 |
| `volatility_breakout_v1` | 25 | −7,98 | 30,35 | +2,01 | −17,97 |
| celkem | 82 | −10,63 | 28,79 | −5,40 | −15,87 |

(Meze: `průměr ± 1,645 · sd/√n`, výběrová sd.)

| Výstup | n | WIN | průměr `pnl_pct` | průměr MFE / MAE (bps) | průměr držení |
|---|---:|---:|---:|---:|---:|
| SL | 44 | 0 | −0,3516 % | +9,7 / −26,2 | 302 s |
| TP | 26 | 26 | +0,2762 % | +36,6 / −6,3 | 337 s |
| TIMEOUT | 12 | 2 | −0,036 % | +26,2 / −12,2 | 900 s |

Další fakta:

- MFE ≥ 20 bps dosáhlo 45 z 82 obchodů, MAE ≤ −20 bps 46 z 82. Exkurze jsou symetrické.
- Podíl TP z rozhodnutých obchodů: 26/70 = 37 %. Driftless náhodná procházka
  s bariérami +35/−25 bps: 25/60 = 41,7 %. Break-even z realizovaných průměrů
  (+27,6 / −35,2 bps): asi 56 %.
- Průměrná ztráta (−10,6 bps) ≈ modelované náklady 9 bps
  (`PAPER_FEE_PCT=0.0008`, `PAPER_SLIPPAGE_PCT=0.0001`). Hrubý edge ≈ 0.
- Serverový `.env`: `PAPER_TP_ZONE_BPS=35`, `PAPER_SL_ZONE_BPS=25`.
  `PAPER_MAX_POSITION_AGE_S=900`. Tempo asi 11 obchodů denně.

## 2. Nálezy v kódu

Každý nález má uvedeno, jak ho ve Fázi A ověřit.

**N1 — Sběr evidence nemá stop pravidlo.**
- `signal_router.evaluate_signal_for_paper_entry()` počítá statistiku segmentu
  jen v bloku `if not registration.evidence_only and not signal.evidence_only and not is_quarantined:`.
  Všechny P0.8+ strategie mají v `build_registration()` `evidence_only=True`.
- `p0_8_plus_shadow_evaluator.evaluate_symbol()` routeru nepředává `closed_trades`
  (výchozí `()`).
- `paper_trade_executor.open_paper_position()` u bucketu
  `P0_8_PLUS_EVIDENCE_COLLECTION` rozhodnutí routeru přebírá
  (větev s logem `[P0_8_PLUS_ADMISSION_TRUSTED]`).
- Důsledek: ztrátová strategie obchoduje neomezeně dlouho.

**N2 — Predikce se neukládá k uzavřenému obchodu.**
- `_expected_move_bps()` ve strategiích vrací heuristiku
  (např. `min(|distance_from_mean_bps| × 0.6, atr_bps × 1.5)`), vždy `is_cold_start=True`.
- Pipeline ji předá jako `extra["expected_move_pct"] = gross_expected_move_bps / 10000`
  (pozor: navzdory názvu je to u P0.8+ **zlomek**, ne procento) a
  `signal["ev"] = max(0, net_expected_edge_bps / 10000)`.
- Slovník pozice v `open_paper_position()` obě hodnoty nese
  (`"expected_move_pct"`, `"ev_at_entry"`), a `close_paper_position()` staví
  `closed_trade = {**pos, ...}`, takže se do `save_closed_trade()` dostanou.
- `local_persistent_cache.save_closed_trade()` je ale do tabulky `closed_trades`
  nezapisuje — nemá pro ně sloupec. Kalibraci predikce proti realitě tedy
  z databáze nejde spočítat.

**N3 — Vlastní geometrie strategií se nepoužije (jen kontext, neřešit).**
Pipeline předává `extra["tp_from_executor"]`/`["sl_from_executor"]`, ale blok
`if os.getenv("PAPER_TP_ZONE_BPS"):` v `open_paper_position()` je přepíše env
hodnotami. Moduly `mean_reversion_exit_v1` a `dynamic_breakout_exit_v1`
neexistují, jsou to jen štítky v `tp_sl_profile`.

**N4 — Adaptivní učení je rozpojené (jen kontext, neřešit).**
- `PaperAdaptiveLearning.regime_tp_strategy` nemá klíč `SIDEWAYS` a jeho výstup
  přebíjí env TP. Pravidlo při WR < 45 % TP rozšiřuje.
- `segment_weights` čte jen `paper_training_sampler.py`, jehož vstupní API bylo
  odstraněno 2026-09-22.

**N5 — Papírové náklady jsou optimistické.**
`RESEARCH_M5_COST_ARITHMETIC.md`: dosažitelný tier Binance spot (VIP0 + BNB) je
asi 15 bps round-trip pro maker i taker. Paper počítá 9 bps.

## 3. Co už bylo vyvráceno — NEOPAKOVAT

Tyto směry mají v repu hotový out-of-sample výzkum se záporným výsledkem.
Nenavrhuj je jako řešení a neimplementuj je:

- z-score mean reversion, breakout, time-series momentum, cross-sectional
  momentum, tail residual reversal, DEV_FADE — `RESEARCH_COSTWALL_FINDINGS.md`;
- delší horizont (1h svíčky), fixní i walk-forward adaptivní —
  `RESEARCH_LONGHORIZON_FINDINGS.md`;
- maker exekuce jako cesta k nižším nákladům — `RESEARCH_M5_COST_ARITHMETIC.md`;
- funding carry — `RESEARCH_FUNDING_CARRY_FINDINGS.md`;
- ladění TP/SL na stávajících signálech —
  `_workspace/43_timeout_dominance_no_edge_confirmation.md`.

Pravidla pro jakýkoli budoucí kandidátní signál: `RESEARCH_PIVOT_CHARTER.md`.

Cílem tohoto zadání **není najít ziskovou strategii**. Cílem je, aby systém
poctivě měřil, uměl sám přestat a ukládal data potřebná ke kalibraci.

---

## 4. Fáze A — vlastní analýza (bez změn kódu)

1. Přečti `AGENTS.md` a soubory uvedené u N1–N2.
2. Každý nález N1–N5 označ `CONFIRMED` / `REFUTED` / `NOT_VERIFIED` s odkazem
   `soubor:řádek`. Pokud některý vyvrátíš, zastav se u něj a popiš proč —
   navazující úkol pak neimplementuj naslepo.
3. Z evidence JSON přepočítej tabulky z části 1. Neshodu nahlas.
4. Spusť výchozí sadu testů (část 7) a zaznamenej výsledek. Referenční hodnota
   z 2026-10-02: **311 passed, 0 failed**.
5. Pokud při analýze najdeš další problém související se strategií nebo učením,
   zapiš ho do reportu jako nový nález. Neopravuj ho, pokud nespadá do úkolů 1–4.

## 5. Fáze B — úkoly

Pořadí je závazné. Každý úkol je samostatně revertovatelný.

### Úkol 1 — Čistý modul stop pravidla

Nový soubor `src/services/evidence_budget.py`. Čistá logika bez I/O, bez importu
brokeru, Firebase nebo event busu (vzor: `src/services/p0_segment_ev_gate.py`).

```python
@dataclass(frozen=True)
class EvidenceBudgetDecision:
    allowed: bool
    code: str            # "CONTINUE" | "STOP_NO_EDGE" | "STOP_BUDGET_EXHAUSTED" | "INVALID_HISTORY"
    n: int
    mean_net_bps: float | None
    upper_bound_bps: float | None   # průměr + z·sd/√n
    lower_bound_bps: float | None   # průměr − z·sd/√n

def decide_evidence_budget(
    net_pnl_bps: Sequence[float],
    *,
    min_n: int = 40,
    max_n: int = 150,
    z: float = 1.645,
) -> EvidenceBudgetDecision: ...
```

Pravidla (v tomto pořadí):

1. Nečíselná hodnota, NaN nebo nekonečno → `INVALID_HISTORY`, `allowed=False`.
2. `n < min_n` → `CONTINUE`.
3. `horní mez < 0` → `STOP_NO_EDGE`.
4. `n >= max_n` a `dolní mez <= 0` → `STOP_BUDGET_EXHAUSTED`.
5. Jinak `CONTINUE`.

`sd` je výběrová směrodatná odchylka (`n − 1`). Při `sd == 0` jsou obě meze rovné
průměru. V docstringu uveď, že obchody nejsou nezávislé, takže mez je orientační.

Testy `tests/test_evidence_budget.py`:

- hranice `min_n` a `max_n`, všechny čtyři kódy, nulová odchylka, neplatné
  vstupy, prázdná řada, determinismus;
- test nad skutečnými daty z evidence JSON (načíst soubor, `pnl_pct × 100`):
  `sideways_mean_reversion_v1` → **`STOP_NO_EDGE`** (n = 57, horní mez ≈ −5,64),
  `volatility_breakout_v1` → **`CONTINUE`** (n = 25 < 40).

### Úkol 2 — Zapojení stop pravidla do routeru

Soubory: `src/services/strategy_contracts.py`, `src/services/signal_router.py`,
`src/services/p0_8_plus_shadow_evaluator.py`.

1. Do `strategy_contracts.py` přidej konstantu
   `P0_REJECT_EVIDENCE_BUDGET = "P0_REJECT_EVIDENCE_BUDGET"` vedle ostatních `P0_*`.
2. Do `evaluate_signal_for_paper_entry()` přidej volitelný keyword parametr
   `evidence_budget_fn: Optional[Callable[[str], EvidenceBudgetDecision]] = None`
   (argument: `signal.learning_source`). Stejný vzor injekce jako `risk_guard_fn`.
   Výchozí `None` = nulová změna chování.
3. Vyhodnoť ji jen tehdy, když by rozhodnutí P0 jinak bylo
   `P0_ADMIT_EVIDENCE_COLLECTION`, a to **před** voláním risk guardu.
   Při `allowed=False` vrať `admitted=False`,
   `decision_code=P0_REJECT_EVIDENCE_BUDGET`, v `decision_reasons` kód, `n`,
   průměr a meze. Výjimka z funkce = zamítnutí (fail-closed).
   Cesta `P0_ADMIT_STRICT_EV` a všechna dřívější zamítnutí se nemění.
4. V `p0_8_plus_shadow_evaluator.py` přidej funkci, která:
   - čte tabulku `closed_trades` z `local_persistent_cache.LOCAL_DB_PATH`
     v režimu `mode=ro` (vzor čtení: `_should_skip_segment_p0_strict_ev()`
     v `paper_trade_executor.py`);
   - bere řádky daného `learning_source`; pokud
     `performance_epoch.load_epoch(LOCAL_DB_PATH)` vrátí epochu, jen řádky
     s `entry_ts >= started_at`, jinak všechny;
   - vrací `decide_evidence_budget([pnl_pct * 100, ...])`;
   - výsledek cachuje 60 s na `learning_source`;
   - při chybě čtení vrací rozhodnutí `allowed=False`, `code="INVALID_HISTORY"`.
5. `evaluate_symbol()` ji routeru předá jen při
   `PAPER_EVIDENCE_STOP_RULE_ENABLED` ∈ {`1`,`true`,`yes`,`on`} (výchozí vypnuto).
   Práh `min_n`/`max_n` čti z `PAPER_EVIDENCE_STOP_MIN_N` / `PAPER_EVIDENCE_STOP_MAX_N`
   s výchozími 40 / 150; neplatná hodnota → výchozí.
6. Při zamítnutí zaloguj jednou za 300 s na `learning_source` řádek
   `[P0_EVIDENCE_BUDGET_STOP] learning_source=… code=… n=… mean_bps=… upper_bps=…`.
7. Stonkfly se nedotýkej; zůstává zamítnuté dřív přes `REJECT_SHADOW_ONLY`.

Testy:

- `tests/test_signal_router.py`: bez parametru beze změny; `allowed=False` →
  `P0_REJECT_EVIDENCE_BUDGET` a risk guard se nezavolá; výjimka → zamítnutí;
  strict-EV cesta funkci nevolá; signál zamítnutý dřív (náklady, karanténa)
  funkci nevolá.
- `tests/test_p0_8_plus_shadow_evaluator.py`: příznak vypnutý → funkce se
  nepředává; zapnutý → předává; čtení z dočasné SQLite v `tmp_path` včetně
  filtru epochy; cache 60 s; chyba čtení → `INVALID_HISTORY`.
- `tests/test_signal_router_bypass.py` a
  `tests/test_p0_8_plus_shadow_evaluator_bypass.py` musí dál procházet beze změny.

### Úkol 3 — Uložení predikce k uzavřenému obchodu

Jediný měněný produkční soubor: `src/services/local_persistent_cache.py`.
**`paper_trade_executor.py` se nemění** — potřebná pole už v `closed_trade` jsou.

1. Přidej sloupce `predicted_gross_move_bps REAL` a `predicted_net_edge_bps REAL`
   stejným idempotentním vzorem `ALTER TABLE ... ADD COLUMN`, jaký soubor používá
   pro `_attribution_cols`.
2. V `save_closed_trade()` je zapiš **jen** pro obchody s
   `explore_bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"`:
   - `predicted_gross_move_bps = expected_move_pct × 10000`,
   - `predicted_net_edge_bps = ev_at_entry × 10000`.
   U ostatních obchodů a při chybějící nebo nekonečné hodnotě zapiš `NULL`
   (u starší cesty má `expected_move_pct` jiné jednotky).
3. Staré řádky zůstávají `NULL`. Žádný backfill, žádná migrace dat.
4. Testy rozšiř v `tests/test_local_persistent_cache_attribution.py`:
   P0.8+ obchod → obě hodnoty správně; jiný bucket → `NULL`; chybějící pole →
   `NULL`; databáze bez nových sloupců se při inicializaci doplní.

Omezení: `predicted_net_edge_bps` je kvůli `max(0, …)` v pipeline zdola oříznuté
nulou. Uveď to v docstringu, neopravuj.

### Úkol 4 — Read-only report epochy

Nový skript `scripts/research/p0_8_plus_epoch_report.py`.

Vstupy: `--db PATH` (SQLite, otevírat jen `mode=ro`) **nebo** `--json PATH`
(formát evidence souboru), `--since UNIX` (volitelné), `--out DIR`.
Žádná síť, žádný zápis mimo `--out`.

Výstup `report.json` + `report.md`, po `learning_source` a celkem:

- n, WIN/LOSS/FLAT, rozpad podle `exit_reason`;
- průměr čistého výsledku v bps, sd, a blokový bootstrap 95% interval
  (bloky = kalendářní dny UTC podle `exit_ts`, pevný seed, 2000 opakování);
- výsledek `decide_evidence_budget` pro danou řadu;
- podíl TP z obchodů ukončených TP nebo SL, vedle něj hodnota náhodné procházky
  `SL/(TP+SL)` z mediánu realizovaných MAE u SL a MFE u TP, a break-even podíl
  z realizovaných průměrů `pnl_pct`;
- podíly obchodů s MFE ≥ X a MAE ≤ −X pro X ∈ {10, 20, 30, 35};
- kalibrace: predikovaný vs. realizovaný hrubý pohyb (kde sloupce z úkolu 3
  chybí nebo jsou `NULL`, uveď `NO_DATA`, ne nulu);
- přepočet průměru při nákladech 9 a 15 bps
  (`net15 = net9 − 6 bps`; uveď jako aproximaci).

Prázdný vstup → `NO_DATA`. Skript nic nedoporučuje a nevyhlašuje edge.

Testy `tests/test_p0_8_plus_epoch_report.py`: syntetická DB v `tmp_path`,
a běh nad evidence JSON musí vrátit n = 82 a průměry z tabulky v části 1
(tolerance 0,01 bps).

---

## 6. Tvrdá omezení

Soubory, které se nesmí měnit:

```
src/services/paper_trade_executor.py
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/execution_engine.py
src/services/p0_segment_ev_gate.py        (prahy n>=30, PF>=1.2, timeout<=60 % zůstávají)
src/services/cost_model.py
src/services/paper_adaptive_learning.py
src/services/strategy_*_v1.py             (žádné ladění prahů ani geometrie)
src/services/p0_8_plus_live_pipeline.py
src/services/stonkfly/**
src/core/runtime_mode.py
systemd/**, .github/**, start.py, bot2/main.py
CLAUDE.md, AGENTS.md
docs/codex_prompts/evidence/**
```

Zakázané akce: viz `AGENTS.md`, oddíl „Nikdy“. Zejména žádný commit/push/reset,
žádný SSH ani deploy, žádný zápis do runtime dat, žádné nové závislosti, žádné
nové obchodní větve ani strategie.

## 7. Testy a akceptace

Výchozí sada (spustit před změnou i po ní):

Jeden příkaz na jednom řádku (funguje v PowerShellu i v bashi), spouštět
z kořene repozitáře:

```
python -m pytest -q -p no:cacheprovider tests/test_signal_router.py tests/test_signal_router_bypass.py tests/test_cost_model.py tests/test_p0_segment_ev_gate.py tests/test_p0_8_plus_shadow_evaluator.py tests/test_p0_8_plus_shadow_evaluator_bypass.py tests/test_p0_8_plus_live_pipeline.py tests/test_p0_8_plus_config_validation.py tests/test_p0_8_plus_document_invariants.py tests/test_strategy_sideways_mean_reversion_v1.py tests/test_strategy_sideways_mean_reversion_v1_bypass.py tests/test_strategy_volatility_breakout_v1.py tests/test_strategy_trend_cost_aware_v1.py tests/test_local_persistent_cache_attribution.py
```

Referenční výsledek před změnou (2026-10-02, Python 3.14.3, Windows):
**311 passed, 0 failed**. Celou sadu `tests/` nespouštěj — obsahuje staré
selhávající testy a některé sahají na lokální runtime soubory.

Akceptační kritéria:

1. Výchozí sada + nové testy: 0 failed.
2. S vypnutým `PAPER_EVIDENCE_STOP_RULE_ENABLED` je chování routeru a evaluátoru
   stejné jako před změnou (doloženo testem).
3. Mutační kontrola (úkol 1 a 2): dočasně (a) otoč nerovnost u `STOP_NO_EDGE`,
   (b) odstraň fail-closed větev při výjimce v routeru. Každá mutace musí shodit
   aspoň jeden test. Mutaci vrať a v reportu uveď, který test ji zachytil.
4. Kontrola runtime dat: SHA-256 souborů z `AGENTS.md` (oddíl „Runtime data“)
   před během testů a po něm je shodné.
5. `git status --short` neukazuje změnu v žádném souboru z části 6.

## 8. Fáze C — závěrečný report

Soubor `_workspace/50_codex_strategy_learning_report.md`:

- tabulka nálezů N1–N5 se stavem z Fáze A a odkazy `soubor:řádek`;
- nové nálezy z vlastní analýzy (pokud jsou);
- seznam změněných a nových souborů po úkolech;
- přesné příkazy testů a počty PASS/FAIL/SKIP před změnou a po ní;
- výsledky mutační kontroly;
- výstup `report.md` z úkolu 4 nad evidence JSON;
- co nebylo uděláno a proč (`NOT_RUN` je v pořádku, zamlčení ne);
- hranice rollbacku pro každý úkol.

Report nesmí tvrdit nic o ziskovosti. Testy kódu nejsou důkaz edge.

## 9. Co zůstává na operátorovi (neimplementovat)

- Zapnutí `PAPER_EVIDENCE_STOP_RULE_ENABLED` na serveru a nasazení.
- N3: zda P0.8+ strategie mají používat vlastní TP/SL místo env 35/25.
- N4: zda rozpojené učení odstranit, nebo znovu zapojit.
- N5: zda paper přepnout na náklady 15 bps.
- Zda po zastavení strategie pokračovat dalším kandidátem podle
  `RESEARCH_PIVOT_CHARTER.md`, nebo cíl přehodnotit.
