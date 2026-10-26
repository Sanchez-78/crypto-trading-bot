# Codex zadání: vyhodnocení učícího experimentu PAPER (2026-10-26)

**Pro:** Codex (analýza + implementace). **Review:** Claude / operátor.
**Repozitář:** `C:\Projects\CryptoMaster_srv`, větev `main`, pracovní strom je záměrně dirty.
**Režim:** pouze PAPER. Žádný deploy, push ani přístup na server.
Obecná pravidla: `AGENTS.md`. Předchozí zadání (stop pravidlo, kalibrační sloupce,
report) je hotové — `_workspace/50_codex_strategy_learning_report.md`.

Postup: **Fáze A** (ověř fakta, nic neměň) → **Fáze B** (tři úkoly) → **Fáze C** (report).

---

## 1. Co se od 2. 10. změnilo (souhrn z `docs/remediation/`)

| Datum | Vydání | Podstata |
|---|---|---|
| 08.10. | `UNIFIED_ENGINE_2026-10-08.md` | Jeden scheduler, stop pravidlo zapojené do routeru. |
| 13.10. | — | Stop pravidlo zastavilo obě strategie (`STOP_NO_EDGE`), obchodování ustalo. |
| 15.10. | `DECISION_STATUS_2026-10-15.md` | Lokální snapshot rozhodnutí pro dashboard. |
| 19.10. | `PAPER_LEARNING_2026-10-19.md` | `paper_source_learning_v1`: adaptivní výběr vstupů (EWMA, prior, logistická pravděpodobnost 10–90 %), 20 % CONTROL, WARMUP, PROBE. Stop pravidlo vypnuto, obě politiky současně jsou chyba konfigurace. |
| 20.10. | `STONKFLY_CONTEXT_2026-10-20.md` | Frozen Stonkfly bucket jako kontext pro BTC (`paper_source_learning_stonkfly_v1`). |
| 23.10. | `PAPER_PROBES_2026-10-23.md` | Dokončené svíčky, profily `_closed_v2` a `_paper_probe_v2`; **průzkum povoluje vstupy i se záporným modelovaným edge** (do −15 bps, max 6/h a 48/24 h). BTC odblokován. |

Živé příznaky ke 26. 10. (ověřeno z `/proc/<pid>/environ`):
`PAPER_ADAPTIVE_EXPLORATION_ENABLED=true`, `PAPER_COST_EXPLORATION_ENABLED=true`,
`PAPER_COMPLETED_CANDLE_LEARNING_ENABLED=true`, `PAPER_STONKFLY_CONTEXT_ENABLED=true`,
`PAPER_UNIFIED_ENGINE_ENABLED=true`, `PAPER_EVIDENCE_STOP_RULE_ENABLED=false`,
TP/SL 35/25 bps, náklady 8+1 bps, max držení 900 s.

## 2. Data

`docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261026.json` —
všech 267 uzavřených obchodů epochy `629c052e…` (od 2026-09-25 06:01:52 UTC
do 2026-10-26 04:51 UTC), read-only export ze serveru. Obsahuje
`predicted_gross_move_bps`, `predicted_net_edge_bps` a `tags_json`.

Formát `tags_json`: JSON seznam řetězců `"<policy_version>:<JSON objekt>"`,
např. `paper_source_learning_v1:{"policy_action":"CONTROL","policy_probability":1.0,…}`.
Řádky bez tagu (113) jsou obchody před zavedením politiky.

**Starší soubor `epoch_20260925_closed_trades.json` (82 řádků) neměň** — čtou ho
existující testy.

### Referenční hodnoty (bps = `pnl_pct × 100`, meze = průměr ± 1,645·sd/√n)

| Skupina | n | průměr | sd | dolní mez | horní mez |
|---|---:|---:|---:|---:|---:|
| celkem | 267 | −10,2096 | 24,1136 | −12,6372 | −7,7820 |
| bez politiky (před 19. 10.) | 113 | −11,9145 | 27,6303 | −16,1903 | −7,6388 |
| `paper_source_learning_v1` / ADAPTIVE | 59 | −7,8100 | 18,1280 | −11,6923 | −3,9277 |
| `paper_source_learning_v1` / CONTROL | 68 | −12,1429 | 19,2449 | −15,9820 | −8,3039 |
| `paper_source_learning_v1` / PROBE | 9 | −11,5189 | 20,5597 | −22,7925 | −0,2453 |
| `paper_source_learning_v1` / WARMUP | 13 | +7,4392 | 34,2986 | −8,2092 | +23,0876 |
| `paper_source_learning_stonkfly_v1` / WARMUP | 5 | −17,2300 | 25,2910 | −35,8357 | +1,3757 |

ADAPTIVE − CONTROL = **+4,33 bps**, Welch 95% interval **[−2,17; +10,84]**.
Celkové čisté P/L −2,04447 USD (notional 7,5 USD).

Podle `learning_source`:

| Zdroj | n | průměr | horní mez |
|---|---:|---:|---:|
| `trend_cost_aware_paper_probe_v2` | 84 | −10,75 | −7,30 |
| `sideways_mean_reversion_v1` | 81 | −13,08 | −8,20 |
| `sideways_mean_reversion_paper_probe_v2` | 53 | −10,36 | −6,44 |
| `volatility_breakout_v1` | 42 | −5,16 | +3,36 |
| `volatility_breakout_paper_probe_v2` | 7 | +0,27 | +13,52 |

Kalibrace (predikovaný vs. realizovaný hrubý pohyb se znaménkem, jen řádky
s predikcí):

| Zdroj | n | predikce gross | predikce net | realizace gross | korelace |
|---|---:|---:|---:|---:|---:|
| `trend_cost_aware_paper_probe_v2` | 84 | +1,8 | −12,6 | −1,8 | −0,18 |
| `sideways_mean_reversion_paper_probe_v2` | 53 | +7,2 | −7,2 | −1,4 | +0,19 |
| `volatility_breakout_v1` | 9 | +27,8 | +11,7 | +4,8 | +0,13 |
| `sideways_mean_reversion_v1` | 8 | +19,5 | +5,0 | −1,2 | −0,69 |
| `volatility_breakout_paper_probe_v2` | 7 | +19,7 | +2,5 | +9,3 | +0,32 |

(Hodnoty z prvotního read-only dotazu; tvůj přepočet je autoritativní, neshodu nahlas.)

## 3. Nálezy k ověření (Fáze A)

Každý označ `CONFIRMED` / `REFUTED` / `NOT_VERIFIED` s odkazem `soubor:řádek`
nebo výpočtem z dat.

- **F1 — Adaptivní výběr zatím nemá prokázaný účinek.** Rozdíl ADAPTIVE − CONTROL
  je kladný, ale interval obsahuje nulu. Obě ramena mají horní mez pod nulou.
- **F2 — Průzkum platí za data předvídatelnou ztrátu.** Profily `_paper_probe_v2`
  mají predikovaný net −7 až −13 bps a realizovaný průměr ≈ −10 bps. Ověř v
  `paper_source_learning.py` / `signal_router.py`, že průzkum nemá žádný vlastní
  strop kumulativní ztráty (jen frekvenční rozpočet v `paper_learning_budget.py`).
- **F3 — Predikce hrubého pohybu je nadsazená a téměř nekorelovaná.** U
  cost-positive profilů je predikce o 15–23 bps vyšší než realizace (malé n).
- **F4 — Stonkfly kontext nemá evidenci:** 5 obchodů, vše WARMUP.
- **F5 — Starý `PaperAdaptiveLearning.record_close` tyto obchody nedostává**,
  protože `p0_8_plus_evidence_collection` není v
  `paper_close_pipeline.ELIGIBLE_PAPER_SOURCES` (tvrzení z
  `DECISION_STATUS_2026-10-15.md`).
- **F6 — WR je u dynamických výstupů zavádějící.** `HARD_STOP_STRUCTURAL`
  (36 obchodů, průměr ≈ −1 bps) se počítá jako LOSS.
- **F7 — Konfigurace vylučuje současné zapnutí stop pravidla a adaptivní
  politiky.** Ověř validaci a její test.

Nové nálezy zapiš, ale neopravuj mimo úkoly níže.

## 4. Fáze B — úkoly

### Úkol 1 — Čistý modul verdiktu experimentu

Nový `src/services/learning_experiment_verdict.py`. Bez I/O, bez importu
brokeru/Firebase/event busu. Vzor: `src/services/evidence_budget.py`.

```python
@dataclass(frozen=True)
class ArmStats:
    n: int
    mean_bps: float | None
    sd_bps: float | None
    lower_bps: float | None   # jednostranná 95% mez (z=1.645)
    upper_bps: float | None

@dataclass(frozen=True)
class ExperimentVerdict:
    codes: tuple[str, ...]
    adaptive: ArmStats
    control: ArmStats
    diff_bps: float | None
    diff_low_bps: float | None    # Welch, oboustranný 95% interval (z=1.96)
    diff_high_bps: float | None

def evaluate_selection_experiment(
    adaptive_bps: Sequence[float],
    control_bps: Sequence[float],
    *,
    min_arm_n: int = 30,
    min_effect_n: int = 100,
) -> ExperimentVerdict: ...
```

Předem stanovená pravidla (kódy se mohou kombinovat, pořadí v n-tici podle seznamu):

1. Neplatná hodnota v kterémkoli rameni → pouze `INVALID_DATA`.
2. Pro každé rameno s `n >= min_arm_n`: `upper < 0` → `<ARM>_NO_EDGE`,
   `lower > 0` → `<ARM>_POSITIVE` (ARM = `ADAPTIVE` / `CONTROL`).
3. Pokud některé rameno má `n < min_effect_n` → `EFFECT_INSUFFICIENT_DATA`.
4. Jinak: `diff_low > 0` → `SELECTION_EFFECT_POSITIVE`;
   `diff_high < 0` → `SELECTION_EFFECT_NEGATIVE`; jinak `SELECTION_EFFECT_NOT_SHOWN`.

Výběrová sd (`n − 1`). Docstring: obchody nejsou nezávislé, CONTROL je náhodný
podíl kandidátů, ne současně běžící portfolio, meze jsou orientační.

Testy `tests/test_learning_experiment_verdict.py`: všechny kódy, hranice
`min_arm_n` a `min_effect_n`, nulová sd, neplatné vstupy, determinismus, a test
nad novým evidence JSON: očekávané kódy
`("ADAPTIVE_NO_EDGE", "CONTROL_NO_EDGE", "EFFECT_INSUFFICIENT_DATA")`
(ADAPTIVE n = 59, CONTROL n = 68, obě horní meze < 0).

### Úkol 2 — Rozšíření offline reportu

Soubor `scripts/research/p0_8_plus_epoch_report.py` (napsal ho Codex v předchozím
kole; zachovej stávající CLI, výstupy a chování pro starý evidence soubor).

Přidej:

1. **Parser `tags_json`** (formát v části 2). Neplatný tag = položka
   `INVALID_TAG` v počtech, ne pád. Z tagu použij `policy_version`,
   `policy_action`, `policy_probability`; řádek bez tagu = `NO_POLICY`.
2. **Skupiny:** podle `learning_source`, podle profilu (přípona `_v1`,
   `_closed_v2`, `_paper_probe_v2`), podle `(policy_version, policy_action)`.
3. **Experiment:** výstup `evaluate_selection_experiment` pro ADAPTIVE vs CONTROL
   každé `policy_version`, plus denní blokový bootstrap rozdílu průměrů
   (stejný seed a počet replikací jako stávající bootstrap).
4. **Kalibrace po zdrojích:** bias (predikce − realizace), MAE, Pearsonova a
   Spearmanova korelace, tabulka po kvintilech predikce (n, průměr predikce,
   průměr realizace). Realizovaný gross je side-aware návratnost entry/exit ceny
   (stejně jako stávající kód). Méně než 5 párů → `NO_DATA`.
5. **Časová řada:** po UTC dnech n a průměr čistého výsledku, celkem a po
   `policy_action`.
6. Volitelný argument `--since` funguje i pro JSON vstup.

Report dál nic nedoporučuje a nevyhlašuje edge. Výstupy jen pod `--out`,
atomicky, jako dosud.

Testy rozšiř v `tests/test_p0_8_plus_epoch_report.py`: parser tagů (platný,
neplatný, chybějící), skupiny, kalibrace na syntetických datech se známou
korelací, a běh nad novým evidence JSON s referenčními hodnotami z části 2
(tolerance 0,01 bps u průměrů, 0,05 u korelací). Stávající testy nad starým
souborem musí projít beze změny.

### Úkol 3 — Zápis výsledku do dokumentace

Do `src/services/LOGIC.md` přidej krátkou sekci „Vyhodnocení učícího
experimentu“: definice ramen, předem stanovená pravidla z úkolu 1, proč se
nesmí ladit konstanty politiky na stejných datech, a příkaz pro spuštění reportu.

## 5. Tvrdá omezení

Neměnit (vedle seznamu v `AGENTS.md`):

```
src/services/paper_source_learning.py
src/services/paper_learning_budget.py
src/services/paper_neural_context.py
src/services/signal_router.py
src/services/evidence_budget.py
src/services/p0_8_plus_shadow_evaluator.py
src/services/p0_8_plus_live_pipeline.py
src/services/paper_trade_executor.py
src/services/local_persistent_cache.py
src/services/strategy_*_v1.py
src/services/stonkfly/**
docs/codex_prompts/evidence/**
```

Žádná změna živého rozhodování, příznaků, prahů ani konstant politiky.
Toto kolo je jen měření.

## 6. Testy a akceptace

Výchozí sada (jeden řádek, z kořene repozitáře):

```
python -m pytest -q -p no:cacheprovider tests/test_p0_8_plus_epoch_report.py tests/test_evidence_budget.py tests/test_paper_source_learning.py tests/test_paper_learning_budget.py tests/test_paper_neural_context.py tests/test_signal_router.py
```

Referenční výsledek před změnou (2026-10-26, Python 3.14.3, Windows):
**240 passed, 0 failed**; SHA-256 runtime souborů z `AGENTS.md` beze změny.

Akceptace:

1. Výchozí sada + nové testy: 0 failed.
2. Mutace: (a) otoč nerovnost u `ADAPTIVE_NO_EDGE`, (b) vynech podmínku
   `min_effect_n`. Každou musí zachytit aspoň jeden test; mutaci vrať.
3. SHA-256 runtime souborů před/po shodné.
4. `git status --short` bez změny v souborech z části 5.

## 7. Fáze C — report

`_workspace/57_codex_learning_experiment_eval.md`:

- tabulka F1–F7 se stavem a důkazem;
- nové nálezy;
- změněné/nové soubory;
- příkazy testů, PASS/FAIL/SKIP před a po;
- výsledky mutací;
- celý vygenerovaný `report.md` nad novým evidence souborem;
- co nebylo uděláno (`NOT_RUN` je v pořádku);
- hranice rollbacku.

Bez tvrzení o ziskovosti.

## 8. Rozhodnutí operátora (neimplementovat)

- Pokračovat v průzkumu se záporným modelovaným edge, nebo ho zastavit.
- Zavést strop kumulativní virtuální ztráty pro průzkumné profily.
- Kdy experiment vyhodnotit (návrh: až obě ramena dosáhnou n ≥ 100).
- N3/N4/N5 z předchozího zadání (vlastní TP/SL strategií, staré učení, náklady 15 bps).
