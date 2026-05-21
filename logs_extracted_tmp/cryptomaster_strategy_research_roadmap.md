# CryptoMaster — Research: strategie a logika pro zlepšení úspěšnosti a učení

Datum: 2026-05-19  
Cíl: navrhnout výzkumně podložené směry pro CryptoMaster bez okamžitého patchování live/real logiky.

> Shrnutí: aktuální bot už znovu teče a učí se. Další zlepšení nemá být další rychlý patch, ale řízená evoluce: lepší labelování, metriky kvality signálu, kalibrace pravděpodobností, režimová logika, cost-aware rozhodování a validace bez overfittingu.

---

## 1. Aktuální stav z auditů

Poslední audit ukazuje, že sample flow a learning state jsou funkční:

- `PAPER_TRAIN_ENTRY_REAL` > 0
- `PAPER_TRAIN_QUALITY_EXIT` > 0
- `LM_STATE_AFTER_UPDATE` > 0
- `LM_UPDATE_MISMATCH = 0`
- `STATE_MISMATCH_LOGS = 0`
- `COST_EDGE_BYPASS_ACCEPTED = 0`
- hlavní ztrátové příčiny nejsou jednoznačně dominantní: typicky `WRONG_DIRECTION` a `FEE_DOMINATED_MOVE`

Závěr: **není vhodné přidávat další diagnostiku ani tuning naslepo**. Vhodný další krok je navrhnout budoucí learning roadmap a validaci.

---

## 2. Nejvyšší ROI směry

### A) Meta-labeling: oddělit „směr“ od „má cenu obchodovat“

Robot už umí generovat side/směr: BUY/SELL. Největší zlepšení nemusí být v lepším indikátoru, ale v druhém modelu/vrstvě, která rozhodne:

```text
Má se tento signál vůbec obchodovat v tomto režimu, při těchto nákladech a za tohoto očekávaného pohybu?
```

Použití v CryptoMaster:

- primární model: stávající RDE/signal_generator určuje směr
- meta-model: rozhoduje `TRADE / NO_TRADE`
- vstupy: regime, score_raw, score_final, coherence, expected_move_pct, ATR, spread, MFE/MAE historie, symbol, čas, fee_drag
- label: jestli trade po nákladech dosáhl kladného výsledku nebo kvalitního MFE

Implementace až později:
- nejdřív jen offline report nad paper trades
- potom shadow meta-score
- potom paper_train gate
- live/real až po stabilní validaci

Zdrojová opora:
- triple-barrier a meta-labeling řeší nedostatky fixního horizontu a umožňují modelu řešit velikost / no-bet rozhodnutí, zatímco jiný model určuje side.
- Zdroj: https://mlfinpy.readthedocs.io/en/latest/Labelling.html

---

### B) Triple-barrier labely místo jednoduchého win/loss

CryptoMaster už má přirozenou strukturu:

```text
TP = horní bariéra
SL = dolní bariéra
TIMEOUT = vertikální bariéra
```

To přímo odpovídá triple-barrier metodě. Místo učení jen z finálního `WIN/LOSS/FLAT` by měl robot ukládat label:

```text
+1 = TP / profit target hit
-1 = SL / unacceptable adverse move
0  = timeout / no meaningful edge
```

Rozšířené labely pro CryptoMaster:

```text
label_direction_correct
label_fee_viable
label_tp_reachable
label_mfe_quality
label_mae_risk
label_timeout_quality
```

Důležité: labely musí být volatilita-aware, ne pevně podle času nebo absolutního PnL.

Zdroj:
- triple-barrier používá horní, dolní a vertikální bariéru a dynamicky pracuje s volatilitou.
- https://mlfinpy.readthedocs.io/en/latest/Labelling.html

---

### C) Kalibrace pravděpodobností a EV

Robot používá `p`, `EV`, `score`, `coherence`. Pokud `p=0.55`, musí to empiricky znamenat, že v podobných situacích bylo cca 55 % obchodů úspěšných. Jinak EV není spolehlivé.

Doporučené metriky:

```text
Brier score per symbol/regime/bucket
Calibration curve per regime
Expected vs observed winrate
Expected EV vs realized net PnL
Reliability bins: 0.45–0.50, 0.50–0.55, 0.55–0.60...
```

Použití:

```text
calibrated_p = calibrator(raw_p, symbol, regime, bucket)
calibrated_ev = function(calibrated_p, rr, fees, slippage, stability)
```

Neimplementovat hned do live. Nejprve offline + shadow.

Zdroj:
- scikit-learn definuje dobře kalibrovaný model tak, že predikce 0.8 odpovídají přibližně 80% empirické četnosti; doporučuje Brier/log-loss pro hodnocení.
- https://scikit-learn.org/stable/modules/calibration.html

---

### D) Režimová politika: ne jedna strategie pro všechny trhy

Crypto se chová jinak v režimech:

```text
BULL_TREND
BEAR_TREND
RANGING
QUIET_RANGE
HIGH_VOL
```

Aktuální audity ukazují, že část ztrát je `WRONG_DIRECTION` a část fee/low-vol. To je přesně situace, kde se hodí režimová politika:

```text
if QUIET_RANGE:
    require stronger expected_move_pct
    prefer no-trade unless near fee+edge threshold is realistic
if TREND:
    allow momentum continuation
if RANGING:
    prefer mean-reversion only near edges
if HIGH_VOL:
    reduce size, widen SL, require liquidity confirmation
```

Zdroj:
- režimové modely upravují parametry podle stavu časové řady; u kryptoměn se zkoumá použití režimových pravděpodobností a volatility/return quantiles.
- https://link.springer.com/article/10.1007/s42521-024-00123-2

---

### E) Cost-aware rozhodování jako samostatná vrstva

U krátkého horizontu je fee/spread/slippage často hlavní nepřítel. Robot by měl před každým paper/live rozhodnutím vyhodnotit:

```text
expected_gross_move_pct
fee_drag_pct
spread_pct
expected_slippage_pct
net_edge_pct = expected_gross_move - fee - spread - slippage
```

Doporučený gate:

```text
trade_allowed = net_edge_pct > min_edge_by_regime
```

K tomu TCA loop:

```text
predict costs -> execute -> measure realized costs -> update model
```

Zdroj:
- execution research popisuje cyklus „predict, execute, measure, improve“ a modelování volume, volatility, spreadů a trade size pro redukci slippage.
- https://www.talos.com/insights/execution-alphas-in-crypto-markets-predicting-volume-volatility-and-spreads-to-reduce-slippage

---

### F) Contextual bandit pro výběr akce, ne end-to-end RL

Doporučené akce pro bandit:

```text
A0 = no trade
A1 = trade normal TP/SL
A2 = trade tight TP
A3 = trade trailing only
A4 = trade reduced size
A5 = skip low-vol
```

Context:

```text
symbol, regime, score, EV, coherence, ATR, expected_move, spread, time bucket, recent MFE/MAE
```

Reward:

```text
net_pnl_after_cost
or
risk_adjusted_reward = net_pnl - lambda * drawdown - timeout_penalty
```

Proč bandit:
- CryptoMaster má online učení, více režimů a málo dat v některých bucketech.
- Bandit je vhodnější než deep RL pro malé, bezpečné, auditovatelné kroky.
- Action set musí být malý a předem povolený.

Zdroj:
- výzkum algorithmic trading with signals používá strategickou vrstvu a spekulativní contextual-bandit vrstvu, která se učí reward funkce z market features.
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4484004

---

### G) Momentum/mean-reversion musí být režimově oddělené

High-frequency crypto momentum má podle výzkumu potenciál, ale není jeden univerzální parametr pro všechna období. To sedí na CryptoMaster: neoptimalizovat jeden globální TP/SL nebo jeden score threshold.

Praktický návrh:

```text
BULL_TREND:
    continuation/momentum
BEAR_TREND:
    continuation/momentum short
RANGING:
    mean reversion only at range edge
QUIET_RANGE:
    no-trade unless expected move beats fee wall
HIGH_VOL:
    smaller size + stricter execution quality
```

Zdroj:
- studie high-frequency momentum trading s kryptoměnami našla potenciál, ale zároveň žádná jedna parametrizace nebyla nejlepší napříč všemi sample periods.
- https://www.sciencedirect.com/science/article/abs/pii/S0275531919308062

---

### H) Validace bez overfittingu

Před každým budoucím nasazením musí být zaveden standard:

```text
purged walk-forward / CPCV-like split
embargo around labels
no leakage between overlapping trades
report by regime/symbol/time bucket
out-of-sample only
```

Zakázat:

```text
optimalizace na jeden den logů
patch podle 20 obchodů
měnit TP/SL podle jedné attribution vlny
globální threshold bez regime splitu
```

Zdroj:
- běžné K-Fold a walk-forward metody mají u finančních časových řad limity kvůli temporal dependencies a non-stationarity; purged/CPCV metody se používají ke snížení leakage a overfittingu.
- https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

---

## 3. Doporučený roadmap bez okamžitého live zásahu

### Fáze 1 — Research-only / offline
Cíl: z auditů a paper trades vyrobit dataset.

Výstup:
```text
paper_training_dataset.parquet/jsonl
columns:
timestamp, symbol, side, regime, score_raw, score_final, ev, p, coherence,
expected_move_pct, atr, spread, tp_pct, sl_pct, hold_limit,
mfe_pct, mae_pct, net_pnl_pct, outcome, attribution, reason,
fee_drag_pct, touched_tp, touched_sl, timeout
```

### Fáze 2 — Offline evaluation
Cíl: zjistit, co opravdu predikuje úspěch.

Reporty:
```text
winrate by regime
avg pnl by regime
mfe_to_tp_ratio by regime
mae_to_sl_ratio by regime
fee viability by symbol
wrong_direction by feature state
calibration bins for p/EV/score
```

### Fáze 3 — Shadow model
Cíl: počítat nové skóre, ale neovlivňovat obchodování.

```text
shadow_meta_trade_prob
shadow_cost_viability
shadow_regime_policy
shadow_action_recommendation
```

### Fáze 4 — Paper-only gate
Cíl: použít model jen v paper_train.

```text
if shadow_meta_trade_prob < threshold:
    skip paper trade
else:
    allow paper trade
```

### Fáze 5 — Live/real až po validaci
Cíl: live/real jen po dlouhém období bez mismatch a s prokazatelným out-of-sample zlepšením.

---

## 4. Co teď určitě nedělat

```text
❌ nepřidávat další široké diagnostické patche
❌ neladit live/real TP/SL
❌ nezvyšovat frekvenci obchodů pro rychlejší učení
❌ nepoužívat martingale / averaging down
❌ nenasazovat deep RL přímo do live
❌ neoptimalizovat podle jednoho 24h okna
```

---

## 5. Nejlepší další prompt pro Claude Code

```markdown
# CryptoMaster Research Task — Learning/Strategy Improvement Without Live Changes

You are a senior quant engineer and Python architect. Analyze the existing CryptoMaster codebase and logs to design an offline research pipeline for improving paper-training learning and future strategy selection.

STRICT SCOPE:
- Do NOT change live/real trading behavior.
- Do NOT tune TP/SL, EV, score thresholds, or execution logic.
- Do NOT add broad diagnostics.
- Build research-only/offline tooling and reports.
- All outputs must be deterministic, auditable, and low-risk.

CONTEXT:
CryptoMaster is an event-driven crypto bot:
market_stream -> signal_generator -> realtime_decision_engine -> trade_executor -> paper_trade_executor -> learning_monitor.
Recent patches restored paper training flow and learning state. Current issue is not blocked flow; it is improving future success and learning quality.

RESEARCH GOALS:
1. Build/export a canonical paper-training dataset from logs and/or local state.
2. Implement triple-barrier-style labels from existing TP/SL/TIMEOUT/MFE/MAE data.
3. Add offline reports for:
   - attribution distribution
   - winrate by symbol/regime/side
   - fee-dominated vs wrong-direction analysis
   - MFE-to-TP and MAE-to-SL ratios
   - calibration of score/EV/p versus realized outcomes
   - regime-specific opportunity quality
4. Design but do not activate:
   - meta-labeling model: TRADE / NO_TRADE
   - cost-aware viability model
   - regime-specific action policy
   - contextual-bandit action selector
5. Produce a Codex implementation prompt for any straightforward coding tasks.

ACCEPTANCE:
- No live/real behavior changes.
- Tests pass.
- Shell scripts pass bash -n.
- Outputs are saved under research/ or scripts/ with clear README.
- Report includes clear "do not patch yet" gates and required sample sizes.
```

---

## 6. Nejlepší další prompt pro Codex

```markdown
# Codex Task — Build CryptoMaster Offline Paper-Training Research Exporter

Implement a research-only exporter and report generator. Do not modify trading logic.

FILES TO ADD:
- scripts/export_paper_training_dataset.py
- scripts/analyze_paper_training_quality.py
- research/README_paper_training_research.md
- tests/test_paper_training_research_export.py

INPUT SOURCES:
- journalctl text export or log file
- data/paper_open_positions.json if needed
- existing structured logs:
  [PAPER_TRAIN_QUALITY_ENTRY]
  [PAPER_TRAIN_QUALITY_EXIT]
  [PAPER_TRAIN_ECON_ATTRIB]
  [PAPER_TRAIN_ECON_SUMMARY]
  [LM_STATE_AFTER_UPDATE]

OUTPUT:
- data/research/paper_training_dataset.jsonl
- data/research/paper_training_summary.md
- data/research/paper_training_summary.json

REQUIRED FIELDS:
timestamp, trade_id, symbol, side, source, training_bucket, entry_regime,
exit_regime, ev, p, score_raw, score_final, coherence, expected_move_pct,
cost_edge_ok, cost_edge_bypassed, entry, exit, tp_pct, sl_pct, mfe_pct,
mae_pct, net_pnl_pct, gross_move_pct, fee_drag_pct, reason, outcome,
attribution, touched_tp, touched_sl, timeout, hold_s, hold_limit_s.

REPORT SECTIONS:
1. Data integrity
2. Attribution distribution
3. Winrate/PnL by regime
4. Winrate/PnL by symbol
5. Direction quality
6. Fee viability
7. MFE/MAE geometry
8. Calibration bins for score_final and EV
9. Candidate recommendations, research-only
10. Explicit "NO LIVE CHANGE" conclusion

CONSTRAINTS:
- Python 3.11+
- No network calls
- No writes to Firebase
- No edits to live trading modules
- Deterministic parsing
- Unit tests with sample log lines
```
