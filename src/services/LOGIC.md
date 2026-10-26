# Mathematical & Trading Logic Deep-Dive

This document details the core mathematical models and trading logic implemented in the HF-Quant 5.0 system.

## 1. Expected Value (EV) Strategy
The system is an **EV-Only Engine**. It does not trade based on simple "buy" signals; instead, it evaluates the mathematical expectancy of every setup.

### A. The EV Formula
The system uses the standard expectancy formula:
$$EV = (win\_prob \times RR) - (1 - win\_prob)$$
- **RR (Risk:Reward)**: Typically fixed at **1.25** in the decision engine (`TP=1.0 * ATR / SL=0.8 * ATR`).
- **win_prob**: The calibrated win probability (see below).

### B. EV Normalization (Tanh)
In `learning_monitor.py`, EV is bounded using a tanh-Sharpe ratio to prevent outliers (caused by near-zero standard deviation) from poisoning the global metrics:
$$true\_ev = \tanh\left(\frac{mean(PnL)}{max(std(PnL), 0.002)}\right)$$
- This ensures $true\_ev \in (-1, +1)$.

---

## 2. Bayesian Online Calibration
A raw "Confidence Score" from an ML model is often biased. The **Calibrator** in `realtime_decision_engine.py` maps these raw scores to empirical win rates.

- **Process**: 
  1. Internal buckets group signals by confidence (0.1 bins: 0.5, 0.6, 0.7...).
  2. For each bucket, it tracks `[wins, total]`.
  3. **Confidence-to-Reality Warp**: If a model predicts 80% confidence but the bucket's empirical WR is 45%, the `win_prob` used for the EV calculation becomes 45%.
- **Minimum Sample Size**: Requires ≥30 trades per bucket before the calibration is considered "Live". Until then, it defaults to a conservative 0.5 prior.

---

## 3. Portfolio Variance & Risk
Unlike simple fixed-percentage sizing, the **Risk Engine** uses a variance-budgeting model that is correlation-aware.

### A. Variance Calculation
Portfolio risk ($\sigma_p$) is calculated using the pairwise correlation heuristic:
$$\sigma_p = \sqrt{\sum r_i^2 + 2 \sum_{i<j} \rho_{ij} r_i r_j}$$
- $r_i$ = Individual position risk (Size × Stop-Loss %).
- $\rho_{ij}$ = Correlation coefficient.

### B. Correlation Heuristics ($\rho$)
To avoid heavy matrix math on every tick, the system uses "Regime-Direction" heuristics:
- **Same Direction + Same Regime**: $\rho = 0.70$ (Strong Concentration)
- **Same Direction + Diff Regime**: $\rho = 0.45$ (Moderate)
- **Opposite Direction**: $\rho = -0.20$ (Natural Hedge)

---

## 4. Signal Micro-Momentum (V6 L4)
To ensure the bot doesn't "catch a falling knife," it uses a micro-momentum check (`_price_history`) in the decision engine:
- It maintains the last 3 price ticks for each symbol.
- **Entry Guard**: A `BUY` signal is only executed if the current price is $\ge$ the average of the last 3 ticks (ensuring a flat or upward micro-drift at the moment of entry).

---

## 5. Order Book Imbalance (OBI)
Calculated in `market_stream.py` and used as a weight in the feature vector:
$$OBI = \frac{BidVolume - AskVolume}{BidVolume + AskVolume}$$
- **$OBI \in (-1, +1)$**: Positive values indicate heavy buying pressure at the top of the book.

## 6. P0.8+ evidence budget and calibration (2026-10-07)

`evidence_budget.decide_evidence_budget()` is a pure stop rule, not an
admission or readiness grant. Net inputs are bps (`closed_trades.pnl_pct * 100`).
Invalid history fails closed. Before 40 observations collection continues;
after that it stops if `mean + 1.645 * sample_sd / sqrt(n) < 0`. At 150 or more
observations it also stops when the lower bound is non-positive. The bounds
are indicative because trades are dependent; `CONTINUE` does not prove edge.

`signal_router` accepts an optional injected budget callback only on
`P0_ADMIT_EVIDENCE_COLLECTION`, after existing gates and before risk. A denied
decision or callback exception returns `P0_REJECT_EVIDENCE_BUDGET`. Strict-EV,
earlier rejections and Stonkfly shadow rejection retain their existing paths.

`PAPER_EVIDENCE_STOP_RULE_ENABLED` defaults off; only `1/true/yes/on` wires
the callback. `PAPER_EVIDENCE_STOP_MIN_N/MAX_N` default to 40/150; malformed
thresholds fall back to defaults. The evaluator reads canonical SQLite via
`mode=ro`, filtering learning source and epoch entry time, with a 60-second
per-source cache. DB identity, epoch or threshold changes invalidate it.
Rejection logs are limited to once per source per 300 seconds. The reader
does not import the write-on-import cache module: until normal startup has
initialized that module, an enabled rule returns `INVALID_HISTORY`. Failed
reads are retried on a later call; no DB is created by the reader.

`local_persistent_cache` adds nullable `predicted_gross_move_bps` and
`predicted_net_edge_bps`. Only exact `explore_bucket=P0_8_PLUS_EVIDENCE_COLLECTION`
uses `expected_move_pct * 10000` and `ev_at_entry * 10000`. Other paths have
different historical units and stay NULL. Non-finite or missing predictions
also stay NULL; old records are not backfilled. Net predictions already have
a zero floor in the existing pipeline; this change preserves that limitation.

Offline command (no cache-module import, network or trading):

```text
python -B scripts/research/p0_8_plus_epoch_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades.json --out _workspace/strategy-learning-epoch-report-20261007
```

Use `--db PATH` instead of `--json` for read-only SQLite. Optional `--since`
selects `entry_ts >= UNIX`; otherwise all supplied rows are reported. Outputs
are `report.json` and `report.md` under `--out`. Bootstrap resamples complete
UTC exit-day blocks, 2000 times with seed 20261002, preserving unequal block
sizes and trade-weighted means. Few days or dependence between days limits
interpretation. Missing calibration/excursion data is `NO_DATA`, never zero.
Gross calibration compares stored predictions with side-aware entry/exit
returns. The 9→15 bps scenario is only `net15 = net9 - 6`, not a verified fee.
# Jediný scheduler a společná rozhodovací telemetry (2026-10-08)

Opt-in `PAPER_UNIFIED_ENGINE_ENABLED` potlačí duplicitní shadow scheduler,
pokud běží stávající P0.8+ PAPER pipeline. Ta dál používá `evaluate_symbol`
pro běžné strategie i nabídku vstupu Stonkfly. `signal_router` uchovává bounded
souhrny rozhodnutí pro stávající Firebase publisher, nikoli další execution path.
Stonkfly shadow rejection i evidence stop rule jsou v tomtéž přehledu, odděleně
podle strategy ID. Podrobnosti a omezení: `docs/remediation/UNIFIED_ENGINE_2026-10-08.md`.

# Párový Stonkfly ve společném PAPER procesu (2026-10-13)

Opt-in `STONKFLY_PAIRED_ENABLED` zpracuje stejný frame sekvenčně jedním
connectome workerem ve dvou izolovaných stavech. `stonkfly_frozen_paired_v1`
a `stonkfly_plastic_paired_v1` mají oddělenou evidence a společný atomický
checkpoint s kontrolovanou návazností. Registrace obou pozorování sdílí bránu
s evidence tick consumerem. Výsledky procházejí stejným `signal_router`, vždy
shadow-only; metriky používají existující Firebase publisher a quota/outbox.
Plasticity je zapnutá, externí PnL reward zůstává vypnutý do vyřešení kauzální
attribution. Pozorování nejsou portfolio trades ani důkaz edge. Protokol,
obnova a měření: `docs/remediation/STONKFLY_PAIRED_2026-10-12.md`.

# Lokální přehled posledních rozhodnutí (2026-10-15)

`PAPER_DECISION_SNAPSHOT_ENABLED` má výchozí hodnotu false. Při explicitním
zapnutí stávající V5 metrics publisher zapíše omezenou projekci stejných
`decision_engine` a `stonkfly` hodnot, které již předává Firebase payloadu.
`decision_metrics_snapshot` nevolá router ani executor. Pokusy včetně selhání
jsou omezené na jeden za 60 sekund; zápis používá dočasný soubor, fsync a rename.
Výchozí cesta je `local_learning_storage/decision_engine_snapshot.json`.
Na Linuxu má nový soubor 0640; volitelná `PAPER_DECISION_SNAPSHOT_GROUP`
přidělí skupinu pouze tomuto souboru, nikoli existujícím runtime datům.

Samostatný dashboard čte snapshot vedle své cache SQLite. Neplatná data,
soubor nad 32 KiB, budoucí čas nebo stáří přes 900 sekund znamenají neznámý
stav. Web ukazuje poslední verdikt zdroje a samostatný čas kontroly evidence;
z tohoto historického záznamu neodvozuje aktuální oprávnění obchodovat.
Při vypnutí zápisu se již uložený soubor stane zastaralým nejpozději za 900 s.
Žádný nový cloud writer, změna kvóty, obchodní politiky ani learneru.
Podrobnosti: `docs/remediation/DECISION_STATUS_2026-10-15.md`.
# Průběžná PAPER adaptace — 2026-10-19

Volitelný `PAPER_ADAPTIVE_EXPLORATION_ENABLED` vkládá do stávajícího routeru
po P0 evidence admission a před risk čistou policy `paper_source_learning.decide`.
Production adapter čte canonical closed_trades read-only; změny v budoucích
rozhodnutích tak navazují na durable uzavření bez dalšího callbacku nebo state DB.
Verzované skalární metadata prochází SignalEvaluation → extra.tags → position →
close/tags_json → existující Firebase learning payload. Kontrolní kohorta a
periodické probe zachovávají průběžné zkoušení, ztrátové kontexty mají nižší
pravděpodobnost přijetí. Nejde o nový zdroj signálů ani bypass cost/P0/risk.
Detail, invariants, omezení a explicitní přepnutí ze starého permanentního stop
pravidla: `docs/remediation/PAPER_LEARNING_2026-10-19.md`.

# Frozen Stonkfly kontext v PAPER admission — 2026-10-20

Opt-in `PAPER_STONKFLY_CONTEXT_ENABLED` připojí ke stávající BTC evidence policy
skalární feature frozen varianty. Recorder publikuje původní StrategySignal
jen po commitu nové research prediction a mimo svůj zámek. Consumer ověří
úplný frozen/plastic pár; plastic hodnoty zůstávají samostatnou research větví.
Jeden coalesced event probouzí existující entry scheduler pro BTC, bez dalšího
threadu/executoru a bez posouvání pravidelných termínů ostatních symbolů.

`paper_source_learning_stonkfly_v1` odděluje provider/source/profile kohortu
od původní policy; kontext obsahuje frozen bucket, režim a stranu kandidáta.
Učí se z canonical post-cost closed_trades odpovídající kohorty. Deterministický
draw zůstává společný s native kandidátem, takže další inference nedá nový los.
Při nedostupném kontextu zůstává native cesta; již neurálně atribuovaný kandidát
musí navíc projít opakovanou kontrolou čerstvosti před otevřením pozice.

Tags/close/Firebase přenášejí explicitní skalární allowlist. P0, strict EV,
risk, REAL guardy a quota/outbox se neobcházejí; přímý Stonkfly signál stále
neotvírá pozici. Historie a checkpointy se neresetují. Protokol, flagy, vypnutí,
limity a testovací důkazy: `docs/remediation/STONKFLY_CONTEXT_2026-10-20.md`.
# PAPER research cadence (2026-10-23)

`PAPER_COMPLETED_CANDLE_LEARNING_ENABLED` selects finalized 1m snapshots, using
the atomic cache fetch-start cutoff rather than aging partial candles into final
ones. Signals use bar-close timestamps and a separate source/version.
`PAPER_COST_EXPLORATION_ENABLED` explicitly changes cost admission for the
`*_paper_probe_v2` evidence cohort: existing native setups may sample a modeled
net debit down to -15bps with all-in costs <=20bps. Estimates are never inflated.
The existing P0, learner, risk and PAPER executor remain mandatory, with no
strict-EV/readiness grant. Existing immutable close evidence plus open positions
enforce rolling 6/hour, 48/day and 30min/symbol. Final entry rechecks pacing,
freshness and cost, and preserves signed estimates and research-override metadata
through the existing cloud bridge. Defaults are off; see
`docs/remediation/PAPER_PROBES_2026-10-23.md` for boundaries and validation.

## Vyhodnocení učícího experimentu (2026-10-26)

`learning_experiment_verdict.py` je čistý offline výpočet nad post-cost bps,
bez napojení na živé rozhodování. ADAPTIVE a CONTROL se porovnávají zvlášť pro
každou `policy_version`; WARMUP, PROBE, chybějící a neplatné tagy nejsou ramena
tohoto srovnání. CONTROL je náhodný podíl kandidátů před filtrem, nikoli souběžné
portfolio ani pevný podíl uskutečněných obchodů.

Předem stanovené pořadí kódů: neplatná data → pouze `INVALID_DATA`. Pro ADAPTIVE
a potom CONTROL při n ≥ 30 horní mez < 0 → `<ARM>_NO_EDGE`, dolní mez > 0 →
`<ARM>_POSITIVE`. Meze používají výběrovou SD a z=1,645. Má-li některé rameno
n < 100, následuje `EFFECT_INSUFFICIENT_DATA`; jinak rozdíl ADAPTIVE−CONTROL
s Welchovým standard error a předepsaným z=1,96 dává `SELECTION_EFFECT_POSITIVE`
při dolní mezi > 0, `SELECTION_EFFECT_NEGATIVE` při horní mezi < 0, jinak
`SELECTION_EFFECT_NOT_SHOWN`. Nejde o Studentův t interval. Obchody jsou závislé
a ramena podléhají výběru, proto jsou meze orientační a nepotvrzují kauzalitu.

Report navíc losuje společné celé UTC dny uzavření pro obě ramena (seed 20261002,
2 000 replikací). Resample bez některého ramene vynechá a jeho počet uvede.
Kalibrace používá side-aware entry/exit gross, Pearsonovu korelaci, Spearmanovy
průměrné pořadové hodnoty při shodách a kvintily podle predikce; shodné predikce
se nedělí. Pod pět párů je rozšířená diagnostika `NO_DATA`, staré popisné průměry
zůstávají kvůli kompatibilitě. Neplatný policy tag zůstává `INVALID_TAG` a nesmí
se stát CONTROL. `_paper_probe_v2` zachovává zápornou net predikci.

Konstanty politiky, rámce a thresholdy se nesmějí ladit na stejných datech,
na kterých se reportuje výsledek; vznikl by výběrový bias a ztratila by se
nezávislá evidence. Výpočet nemění příznaky, stop pravidlo, portfolio ani učení.
Spuštění z kořene (zápis pouze atomicky pod `--out`; `--since` filtruje entry_ts):

```text
python -B scripts/research/p0_8_plus_epoch_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261026.json --out _workspace/learning-experiment-eval-20261026
```
