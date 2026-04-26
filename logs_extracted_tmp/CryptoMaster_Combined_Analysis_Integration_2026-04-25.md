# CryptoMaster — sjednocená log analýza + integrační plán

Datum: 2026-04-25  
Účel: spojit aktuální runtime analýzu s navazujícím implementačním/integračním plánem do jednoho přehledného `.md` souboru bez nutnosti přepínat mezi více dokumenty.

## Jak tento soubor použít

- Nejprve projdi **analytickou část** a potvrď, že závěry odpovídají aktuálním logům.
- Potom pokračuj na **integrační část**, kde je doporučené pořadí rolloutů.
- Při implementaci drž zásadu: **nejdřív observability a canonical truth, potom sizing/governance, až pak exit economics a model quality vrstvy**.
- Tento soubor je vhodný jako vstup pro Claude Code nebo Codex.

---

# CryptoMaster — log analýza, závěry a návrhy implementace

Datum analýzy: 2026-04-25  
Zdroj: uživatelem dodané runtime logy z Hetzneru (`cryptomaster`)  
Cíl: zhodnotit aktuální stav po nových implementacích, identifikovat hlavní ekonomické blokery a navrhnout další implementační kroky včetně ukázek kódu.

---

## 1. Executive summary

Aktuální stav je **lepší než předchozí snapshoty**, ale systém je stále ve stavu:

- **WR roste**: zhruba `72.9% -> 74.4% -> 76.0%`
- **net ztráta se zmenšuje**: `-0.00095542 -> -0.00090204 -> -0.00066441`
- **PF se zlepšuje**, ale pořád je **pod 1.0**: `0.65 -> 0.71`
- **scratch exit dominance klesá**, ale stále je příliš vysoká: `81% -> 76% -> 72%`
- **partial monetizace funguje**, ale ještě nestačí přebít objem malých ztrátových/flat exitů
- **learning health zůstává BAD**, i když roste: `0.019 -> 0.065`
- **ekonomické skóre v interním monitoru je dobré**, ale jeho interpretace je stále podezřelá vůči hlavním canonical metrikám

### Hlavní závěr
Bot už není ve stavu „úplně zablokovaný“, ale stále je ve stavu:

> **statisticky často vyhrává, ale ekonomicky málo monetizuje výhry a stále příliš často odchází přes scratch/stagnation/replaced.**

To znamená, že hlavní problém už není primárně „nedělá obchody“, ale spíš:

1. **výhry jsou příliš malé**,  
2. **ztrátové a flat exity jsou příliš časté**,  
3. **slabé (sym, regime) buňky stále znečišťují learning i routing**,  
4. **feature layer zůstává slabá a uniformně nekvalitní**,  
5. **některé interní health/economic interpretace si ještě protiřečí s canonical výsledkem.**

---

## 2. Co se zlepšilo oproti dřívějším logům

## 2.1 Profitabilita se zlepšuje

Dříve:
- `WR_canonical = 72.9%`
- `PF = 0.65x`
- `net = -0.00095542`
- `SCRATCH_EXIT = 396`

Nyní:
- `WR_canonical = 76.0%`
- `PF = 0.71x`
- `net = -0.00066441`
- `SCRATCH_EXIT = 362`

To je reálné zlepšení. Není kosmetické.

## 2.2 Monetizace exitů se posouvá správným směrem

Novější snapshot ukazuje:
- `PARTIAL_TP_25 = 59` místo `52` a dříve `47`
- `TP share = 23%` místo dřívějších `19%` a `12%`
- `scratch share = 76%` místo dřívějších `81%` a `88%`
- `harvest rate = 23.0% (34/148)` místo dřívějších `18.6%` a `11.7%`

To znamená, že exit monetization patch má pravděpodobně pozitivní efekt.

## 2.3 Pre-live audit už nefailuje systémově

Dříve bylo vidět:
- `Passed to execution: 0`
- `Blocked: 20`
- `[CI FAIL] blocked_ratio=1.000 > 0.80`

Později:
- `Passed to execution: 19`
- `Blocked: 1`
- `[CI] PASS`

To je zásadní zlepšení. Znamená to, že routing a audit už nejsou totálně přepřísněné nebo deadlocked.

---

## 3. Co zůstává problém

## 3.1 WR je vysoký, ale PF je stále špatný

Nejdůležitější ekonomický rozpor:

- `WR_canonical = 76.0%`
- `Profit Factor = 0.71x`
- `Zisk (uzavrene) = -0.00066441`

To téměř jistě znamená:

- průměrná výhra je příliš malá,
- průměrná ztráta nebo kumulace malých ztrát je stále příliš velká,
- scratch/stagnation/replaced stále „vyžírají“ edge.

### Praktická interpretace
Bot správně trefuje směr dost často, ale:

- buď vstupuje pozdě,
- nebo vybírá příliš brzy,
- nebo drží slabé setupy jen proto, aby skončily ve scratch/stagnation,
- nebo výhru rozmělní přes příliš malé partial profity.

---

## 3.2 Scratch exit pořád dominuje

Aktuální snapshot:

- `SCRATCH_EXIT 362`
- `avg -0.00000264`
- `72% obch`
- `144% pnl`

To je stále největší ekonomický problém systému.

I když je scratch menší než dříve, stále platí:

> hlavní engine zatím generuje více „mikro-ztrát / mikro-flat odchodů“ než skutečně monetizovaných trendových výher.

Navíc:
- `STAGNATION_EXIT 37`
- `replaced 33`
- `EARLY_STOP 2`
- `TIMEOUT_LOSS 1`

To dohromady vytváří velký negativní „exit tax“.

---

## 3.3 Learning monitor je stále slabý

Aktuální stav:
- `Health: 0.065 [BAD]`
- `Edge: 0.000`
- `Conv: 0.077`
- `Stab: 0.000`
- `Breadth: 0.000`

I když ekonomika se zlepšila, learning vrstva stále neukazuje robustní generalizovaný edge.

To znamená, že systém zatím:
- spíše těží z lokálních heuristic/exit zlepšení,
- než že by opravdu dobře „věděl“, **které buňky jsou dlouhodobě dobré**.

---

## 3.4 Slabé buňky jsou stále velmi slabé

Příklady z logu:

- `BNB BEAR_TREND  n=10  EV=-0.001  WR=10%`
- `DOT BEAR_TREND  n=10  EV=-0.000  WR=0%`
- `XRP BEAR_TREND  n=9   WR=11%`
- `SOL BULL_TREND  n=7   WR=29%`
- `ETH BEAR_TREND  n=28  WR=32%  conv=0.96`

To je velmi důležité.

### Závažný poznatek
`ETHUSDT_BEAR_TREND` má:
- dost vzorků (`n=28`)
- vysokou konvergenci (`conv=0.955`)
- ale velmi slabý WR (`32%`)

Taková buňka už není „jen immature“. To už je kandidát na:
- tvrdé omezení,
- blokaci směru,
- nebo přemapování feature/branch routing logiky.

Podobně:
- `DOT BEAR_TREND WR=0%` po `n=10`
- `BNB BEAR_TREND WR=10%`

To už je dostatečně špatné na agresivnější zásah.

---

## 3.5 Feature vrstva je pořád téměř uniformně špatná

Z logu:

- `bounce 42%`
- `pullback 42%`
- `mom 42%`
- `wick 42%`
- `breakout 42%`
- `vol 42%`
- `trend 42%`
- `is_weekend 34%`

To znamená, že feature attribution zatím téměř nerozlišuje kvalitní a nekvalitní signály.

### Interpretace
Buď:
1. feature recording stále není dostatečně granular,
2. feature weights se zatím ještě nepřepisují do rozhodovací logiky dost silně,
3. featury jsou příliš korelované a prakticky redundantní,
4. rozhodování je stále více řízené overlay vrstvami než samotnou feature kvalitou.

---

## 3.6 Velikost pozice roste rychleji než kvalita learningu

V logu:
- `Velikost pozice 1.40x`
- současně `Health: 0.065 [BAD]`
- současně stále `PF=0.71`

To je rizikové.

### Závěr
Sizing layer se zřejmě uvolňuje rychleji, než si to learning quality skutečně zaslouží.

To je přesně typ situace, kdy:
- equity může krátkodobě vypadat lépe,
- ale portfolio risk roste dřív, než je edge skutečně robustní.

---

## 3.7 Economic score stále působí nekanonicky nebo příliš optimisticky

Máš v logu současně:

- hlavní dashboard: `PF = 0.71`
- economic block: `PF: 5.66  Scratch: 47%  Trend: IMPROVING`

To je extrémní rozdíl.

I když se to může počítat nad jiným podmnožinovým oknem, pro produkční řízení je to nebezpečné.

### Závěr
Priority 1 (canonical metrics unification) musí být dotažené i do:
- economic gate,
- learning monitor summary,
- dashboard text output,
- audit overlay,
- CI gate summaries.

Dokud tohle nebude sjednocené, hrozí falešný pocit zlepšení.

---

## 4. Diagnóza podle priority

## Priorita A — největší ekonomický problém

### Exit monetization ještě není dotažená do dostatečné síly

Co funguje:
- partial TP roste,
- scratch share klesá,
- stagnation exits generují i nějaké winners,
- monetization direction je správná.

Co nefunguje dost:
- scratch stále tvoří většinu exit objemu,
- average positive capture je stále moc malý,
- trailing je prakticky nulový,
- final runner harvesting je minimální.

### Dopad
Tohle je stále hlavní důvod, proč PF zůstává < 1.

---

## Priorita B — weak cell suppression je potřeba zpřísnit

Cell quality patch byl dobrý krok, ale z logů plyne, že je vhodné přidat druhý stupeň:

### Doporučení

#### Hard block candidates
Po dosažení `n >= 10`:
- `WR <= 15%` a `EV <= 0` -> hard block branch/cell
- `WR <= 25%` a `conv >= 0.15` -> hard block nebo 0.10x sizing

To se týká zejména:
- BNB/BEAR
- DOT/BEAR
- XRP/BEAR
- možná ETH/BEAR, pokud canonical PnL pro danou cell potvrzuje slabost

---

## Priorita C — feature pruning je potřeba použít agresivněji v runtime

Zatím to vypadá, že feature_quality existuje, ale její dopad do runtime score není dost velký.

### Doporučení
Feature multipliers nedávat jen jako jemnou úpravu confidence, ale:

- použít je při konstrukci `ws` / signal score,
- použít je při branch gating,
- použít je i pro `FORCED_EXPLORE` branch.

Jinak budou slabé feature statistiky jen „hezký report“, ale ne skutečný filtr.

---

## Priorita D — bootstrap/sizing musí být vázaný na kvalitu, ne jen na růst trade count

V logu je pořád:
- `BOOTSTRAP_REDUCED_MODE active (50% position sizing)`
- ale zároveň dashboard ukazuje `Velikost pozice 1.40x`

To je minimálně matoucí, možná logicky nekonzistentní.

### Nutné ověřit
Musí být jasné:
- co je globální sizing multiplier,
- co je bootstrap multiplier,
- co je cell-quality multiplier,
- co je auditor multiplier,
- co je final execution multiplier.

Bez toho nejde auditovat, proč daná pozice nakonec dostala konkrétní velikost.

---

## 5. Konkrétní návrhy implementace

## 5.1 Canonical metrics — dotáhnout do všech reportů

### Cíl
Odstranit jakýkoli rozpor mezi:
- dashboard PF,
- economic PF,
- audit PF,
- CI PF.

### Doporučený pattern

```python
# src/services/metrics_adapter.py
from src.services.canonical_metrics import (
    canonical_profit_factor,
    canonical_win_rate,
    canonical_expectancy,
    canonical_exit_breakdown,
    canonical_overall_health,
)


def build_runtime_metrics(canonical_state: dict) -> dict:
    pf = canonical_profit_factor(canonical_state)
    wr = canonical_win_rate(canonical_state)
    exp = canonical_expectancy(canonical_state)
    exits = canonical_exit_breakdown(canonical_state)
    health = canonical_overall_health(canonical_state)
    return {
        "profit_factor": pf,
        "win_rate": wr,
        "expectancy": exp,
        "exit_breakdown": exits,
        "health": health,
    }
```

### Pravidlo
`economic_gate`, dashboard i audit nesmí používat vlastní PF/WR implementace, jen tento adapter.

---

## 5.2 Hard cell quarantine

### Cíl
Přestat alokovat kapitál do evidentně toxických buněk.

```python
# src/services/cell_quality_penalty.py

def should_quarantine_cell(stats: dict) -> bool:
    n = stats.get("n", 0)
    wr = stats.get("wr", 0.0)
    ev = stats.get("ev", 0.0)
    conv = stats.get("conv", 0.0)

    if n >= 10 and wr <= 0.15 and ev <= 0:
        return True
    if n >= 10 and wr <= 0.25 and conv >= 0.15:
        return True
    return False
```

Použití v RDE:

```python
cell_stats = learning_state.get_pair_stats(sym, regime)
if should_quarantine_cell(cell_stats):
    return reject("CELL_QUARANTINED")
```

### Doporučení
Quarantine logovat samostatně, ne míchat s `FAST_FAIL_SOFT`.

---

## 5.3 Feature multipliers aplikovat do raw score, ne až pozdě

### Cíl
Ať slabé feature opravdu snižují pravděpodobnost průchodu.

```python
def apply_feature_quality(features: dict, feature_pruner) -> dict:
    adjusted = {}
    for name, value in features.items():
        mult = feature_pruner.get_feature_weight_multiplier(name)
        adjusted[name] = value * mult
    return adjusted
```

Pak:

```python
adjusted_features = apply_feature_quality(raw_features, feature_pruner)
ws = compute_weighted_signal_score(adjusted_features)
```

### Důležité
Neaplikovat feature pruning až po výpočtu `p`, ale před vznikem `ws` / `score`.

---

## 5.4 Exit monetization — přidat runner logic

Aktuálně:
- partial TP funguje,
- trailing téměř neexistuje,
- scratch je stále moc dominantní.

### Doporučení
Po `TP1`:
- posunout SL alespoň na break-even minus fees,
- aktivovat runner režim,
- scratch už nepoužívat na celý zbytek stejně agresivně.

```python
def on_tp1_hit(position):
    position.realized_tp1 = True
    position.remaining_size *= 0.75
    position.stop_loss = max(
        position.stop_loss,
        position.entry_price * (1.0 + position.fee_buffer)
    )
    position.runner_mode = True
```

A pro runner:

```python
def get_runner_timeout(regime: str) -> int:
    if regime in {"BULL_TREND", "BEAR_TREND"}:
        return 300
    if regime == "RANGING":
        return 180
    return 150
```

### Efekt
Méně situací, kdy obchod s dobrým začátkem skončí nakonec skoro flat.

---

## 5.5 Stagnation exit rozdělit na weak vs protected stagnation

Aktuálně `STAGNATION_EXIT` obsahuje zřejmě směs:
- rozumných ochranných exitů,
- i předčasného „killování“ obchodů, které měly ještě šanci.

### Doporučení
Rozdělit na dva typy:
- `STAGNATION_EXIT_WEAK`
- `STAGNATION_EXIT_PROTECTED`

A logovat samostatně.

```python
def classify_stagnation_exit(position, pnl, tp1_hit, age_s):
    if tp1_hit or pnl > 0:
        return "STAGNATION_EXIT_PROTECTED"
    return "STAGNATION_EXIT_WEAK"
```

To zlepší audit a ukáže, jestli stagnation exit spíš chrání, nebo ničí edge.

---

## 5.6 Forced explore musí respektovat toxické cells

V logu je vidět:
- forced signals stále vznikají,
- následně padají na `REJECT_NEGATIVE_EV`.

To je lepší než je vzít, ale pořád to zbytečně generuje šum.

### Doporučení
`FORCED_EXPLORE` nepouštět do:
- quarantined cells,
- negative-EV mature cells,
- low-feature-quality branches.

```python
def can_forced_explore(sym, regime, cell_stats, feature_quality_score):
    if should_quarantine_cell(cell_stats):
        return False
    if cell_stats.get("n", 0) >= 10 and cell_stats.get("ev", 0.0) <= 0:
        return False
    if feature_quality_score < 0.45:
        return False
    return True
```

---

## 5.7 HardBlock / idle adaptation zpomalit

V logu:
- `HardBlock zone adjustment: MODERATE (idle=71s, health=0.50) buffer: 0.060 -> 0.090`

Tady je potřeba opatrnost. Když se systém příliš rychle „odblokuje“, může začít brát signály v době, kdy kvalita edge ještě není potvrzená.

### Doporučení
Idle adaptation vázat nejen na idle sekundy, ale i na:
- canonical PF posledních N obchodů,
- learning health,
- weak-cell ratio.

```python
def compute_idle_relaxation(idle_s, lm_health, recent_pf, weak_cell_ratio):
    if recent_pf < 1.0:
        return 0.0
    if lm_health < 0.15:
        return 0.0
    if weak_cell_ratio > 0.35:
        return 0.0
    if idle_s < 300:
        return 0.0
    return min(0.10, (idle_s - 300) / 3000)
```

---

## 5.8 Add “profit capture ratio” metric

Potřebuješ metriku, která lépe vysvětlí, proč je WR vysoký, ale PF nízký.

### Návrh nové metriky

```python
def profit_capture_ratio(gross_wins: float, tp_realized: float) -> float:
    if gross_wins <= 0:
        return 0.0
    return tp_realized / gross_wins
```

Alternativně:
- `runner_capture_ratio`
- `avg_mfe_capture`
- `tp1_to_final_ratio`

### Proč
Tahle metrika ukáže, kolik z potenciální výhry skutečně bot vybral.

---

## 6. Co bych nasadil jako další patch order

## Patch 1 — Canonical metrics enforcement everywhere
Nejdřív sjednotit čísla napříč systémem.

## Patch 2 — Hard quarantine for toxic mature cells
Zabránit ničení edge slabými cells.

## Patch 3 — Stronger runtime feature pruning
Dostat feature kvalitu přímo do score/ws.

## Patch 4 — Runner protection after TP1
Omezit návrat dobrých obchodů do scratch/stagnation.

## Patch 5 — Split stagnation exit taxonomy
Zlepšit audit a rozpoznání, co je ochrana a co destrukce edge.

## Patch 6 — Forced explore constraints
Snížit šum a zbytečné rejecty.

## Patch 7 — Add capture metrics
Začít měřit, kde přesně se ztrácí monetizace.

---

## 7. Praktický verdict k aktuálním logům

### Co je dobrá zpráva
- bot je živý,
- audit passuje,
- obchoduje,
- WR roste,
- net loss se zmenšuje,
- partial TP se zvyšuje,
- scratch dominance pomalu klesá.

### Co je špatná zpráva
- stále to není ekonomicky profitabilní,
- PF 0.71 je stále slabé,
- learning health je pořád BAD,
- feature vrstva je slabá,
- několik cells je evidentně toxických,
- sizing vypadá agresivněji než kvalita edge.

### Nejpravděpodobnější interpretace
Nové moduly pomohly, ale zatím hlavně jako:
- lepší routing,
- lepší audit,
- lepší částečná monetizace.

Ne jako plně stabilní ekonomický engine.

---

## 8. Doporučený cíl pro další fázi

Místo cíle „PF 1.5 rychle“ bych pro další rollout použil realističtější postup:

### Fáze A
- dostat `PF 0.71 -> 0.90+`
- scratch share `72% -> <60%`
- quarantine weak cells
- sjednotit metrics

### Fáze B
- dostat `PF 0.90 -> 1.05+`
- stagnation/protected exit split
- runner protection po TP1
- feature pruning runtime impact

### Fáze C
- dostat `PF 1.05 -> 1.20+`
- kalibrace branch routing
- remove/retrain dead features
- strengthen mature-cell branch bans

Až pak řešit ambicióznější `1.3+`.

---

## 9. Doporučení pro Claude/Codex prompt

Pro další implementační prompt bych zadal přesně toto:

1. **Enforce canonical metrics as sole source of truth** across dashboard, economic gate, audit, CI.
2. **Implement hard cell quarantine** for mature toxic `(sym, regime)` buckets.
3. **Apply feature_quality multipliers before ws/score calculation**, not only as post-hoc reporting.
4. **Protect runners after TP1** with BE+fees stop and longer trend timeout.
5. **Split stagnation exits** into `WEAK` vs `PROTECTED` and report separately.
6. **Restrict forced explore** from toxic cells and low-quality branches.
7. **Add profit capture metrics** (`runner_capture_ratio`, `profit_capture_ratio`, optional `MFE_capture`).
8. **Add regression checks** specifically for scratch share, PF, and toxic-cell capital allocation.

---

## 10. Final conclusion

Aktuální stav není špatný — naopak je vidět měřitelný progres.  
Ale systém zatím ještě není ve stavu, kdy by se dalo říct, že ekonomický problém je vyřešen.

### Nejstručnější pravda

- **decision pipeline je lepší**
- **audit pipeline je lepší**
- **exit monetization je lepší**
- **ale profit extraction je stále slabší než loss/friction leakage**

Proto další krok nemá být „víc obchodů“, ale:

> **tvrdší potlačení toxických cells + silnější runtime pruning + lepší monetizace runnerů + absolutní sjednocení canonical metrik.**

---

## 4. Navazující integrační plán

Goal: integrate the 8 newly implemented modules into the live bot in a controlled, low-regression way. This document is designed as an implementation guide / prompt input for Claude Code or Codex.

---

## 0. Context

Already implemented as standalone modules:

1. `src/services/canonical_metrics.py`
2. `src/services/bootstrap_state_machine.py`
3. `src/services/cell_quality_penalty.py`
4. `src/services/exit_monetization.py`
5. `src/services/probability_calibration.py`
6. `src/services/feature_pruning.py`
7. `src/services/audit_enhancements.py`
8. `src/services/audit_regression_testing.py`

Current situation from logs:

- Canonical WR is high (`~74%`), but PF remains weak (`~0.65x`)
- Scratch exits are still too dominant (`~77–81%`)
- Some cells are clearly weak:
  - `BNB/BEAR` very poor WR
  - `DOT/BEAR` near unusable
  - `BTC BULL/BEAR` negative EV pockets exist
- Audit acceptance improved sharply after recent changes:
  - before: pre-live audit fail / massive blocking
  - now: `19/20 passed`, CI PASS
- Learning health is still low (`BAD`), so rollout must stay conservative

Main rule: **do not integrate all 8 modules at once into live production behavior.**

---

## 1. Integration strategy

Use a staged rollout with explicit feature flags.

### Phase A — observability first
Safe, low-risk, should be merged first:

- `canonical_metrics`
- `audit_enhancements`
- `audit_regression_testing`

### Phase B — capital governance
Moderate risk, changes allocation behavior:

- `bootstrap_state_machine`
- `cell_quality_penalty`

### Phase C — exit economics
Highest likely PF impact, but also high behavioral risk:

- `exit_monetization`

### Phase D — signal/model quality layers
Should be added only after live system is stable with A+B+C:

- `probability_calibration`
- `feature_pruning`

---

## 2. Required feature flags

Create a central config section, for example in `src/config/runtime_flags.py` or equivalent existing config module.

```python
ENABLE_CANONICAL_METRICS = True
ENABLE_AUDIT_ENHANCEMENTS = True
ENABLE_AUDIT_REGRESSION_TESTING = True

ENABLE_BOOTSTRAP_STATE_MACHINE = False
ENABLE_CELL_QUALITY_PENALTY = False
ENABLE_EXIT_MONETIZATION = False
ENABLE_PROBABILITY_CALIBRATION = False
ENABLE_FEATURE_PRUNING = False

ENABLE_SHADOW_PROBABILITY_CALIBRATION = True
ENABLE_SHADOW_FEATURE_PRUNING = True
ENABLE_SHADOW_EXIT_MONETIZATION = True
```

Requirements:

- every module must be independently switchable
- every risky module must support **shadow mode** before live activation
- logs must clearly show whether decision used `LIVE`, `SHADOW`, or `DISABLED`

Example desired log format:

```text
[INTEGRATION] probability_calibration=SHADOW raw_p=0.46 calibrated_p=0.58
[INTEGRATION] feature_pruning=SHADOW feature=breakout raw=1.00 adj=0.70
[INTEGRATION] exit_monetization=LIVE tp1=0.7atr tp2=1.1atr scratch_age=105
```

---

## 3. Canonical metrics integration

### Objective
Eliminate metric inconsistency across dashboard, economic gate, audit, and monitoring.

### Files to update

- dashboard / reporting code
- economic gate / health scoring code
- audit summary code
- learning monitor views
- any place still computing PF, WR, expectancy independently

### Required change
Replace duplicated metric calculations with `canonical_metrics` as the single source of truth.

### Mandatory rules

- no local PF calculation if canonical helper exists
- no local WR calculation if canonical helper exists
- snapshots for audits must use `get_metrics_snapshot()`
- all displayed metrics must use the same closed-trade base

### Implementation sketch

```python
from src.services.canonical_metrics import (
    canonical_profit_factor,
    canonical_win_rate,
    canonical_expectancy,
    canonical_exit_breakdown,
    canonical_overall_health,
    get_metrics_snapshot,
)

pf = canonical_profit_factor(canonical_state)
wr = canonical_win_rate(canonical_state)
exp = canonical_expectancy(canonical_state)
health = canonical_overall_health(canonical_state)
snap = get_metrics_snapshot(canonical_state)
```

### Acceptance criteria

- dashboard PF == audit PF == economic PF
- dashboard WR == audit WR == monitor WR
- one immutable audit snapshot can be compared across runs

---

## 4. Audit enhancements integration

### Objective
Make pre-live audit and decision logs explain *why* trades pass/fail.

### Files to update

- `pre_live_audit.py`
- `realtime_decision_engine.py`
- any signal decision logger

### Required change
Every evaluated signal should call `track_signal_evaluation()` with:

- symbol
- regime
- branch (`normal`, `forced`, `micro`, etc.)
- raw EV
- adjusted EV
- score
- passed / blocked
- bootstrap phase
- failed gate name

### Minimal payload example

```python
track_signal_evaluation(
    sym=sym,
    regime=regime,
    branch=branch,
    ev=ev,
    score=score,
    passed=decision.startswith("TAKE"),
    bootstrap_phase=phase,
    gate_failed=gate_failed,
)
```

### Required report outputs

- pass rate by bootstrap phase
- pass rate by branch
- weak-EV acceptance rate
- top blockers by %
- examples of blocked and accepted borderline trades

### Acceptance criteria

Audit must answer:

- Which branch is failing?
- Which gate blocks the most?
- Are weak-EV trades leaking through?
- Did bootstrap warm/live phases regress?

---

## 5. Audit regression testing integration

### Objective
Turn audit behavior into a regression guardrail.

### Files to update

- `pre_live_audit.py`
- CI runner / audit script / deploy gate

### Required change
After audit report is generated:

1. load previous baseline
2. compare current report
3. emit regression summary
4. fail CI only on meaningful regression thresholds

### Suggested rollout policy

At first:
- warn on regression
- do not hard-fail deploy for 1–2 rollout cycles

After baseline stabilizes:
- fail CI on major regression

### Example flow

```python
baseline = load_audit_baseline()
reg = check_for_regressions(current_report, baseline)
recs = generate_regression_fix_recommendations(reg)
```

### Acceptance criteria

System must detect at least:

- acceptance drop
- branch split deterioration
- weak EV leakage increase
- blocker distribution shift

---

## 6. Bootstrap state machine integration

### Objective
Replace crude trade-count unlock logic with quality-aware state progression.

### Files to update

- `execution.py`
- `realtime_decision_engine.py`
- possibly portfolio sizing path / final size path

### Required behavior
Use bootstrap state per `(sym, regime, branch)`.

State outputs should affect:

- sizing multiplier
- gate relaxation multiplier
- diagnostics / logs

### Recommended integration order

1. add diagnostics only
2. enable sizing multiplier live
3. enable gate relaxation live

### Implementation sketch

```python
from src.services.bootstrap_state_machine import (
    get_bootstrap_state,
    get_sizing_multiplier,
    get_gate_relaxation,
    get_state_diagnostics,
)

state = get_bootstrap_state(sym, regime, branch, lm_state)
size_mult = get_sizing_multiplier(state)
relax_mult = get_gate_relaxation(state)
```

### Important guardrail
Do **not** let bootstrap relaxation override negative EV hard rejection.

Bootstrap may relax:
- score threshold
- cold-start penalties
- fast-fail hardness

Bootstrap must **not** allow:
- negative EV trades
- impossible risk budget
- broken execution quality hard floors

### Acceptance criteria

- hard/soft/normal states visible in logs
- high-quality mature cells unlock sooner than weak immature cells
- no increase in negative EV leakage

---

## 7. Cell quality penalty integration

### Objective
Reduce or block capital allocation to structurally weak symbol/regime cells.

### Files to update

- `execution.py`
- routing / sizing logic
- optional audit report summary

### Required behavior
Use `get_cell_quality_multiplier(sym, regime)` before final size commit.

Optional hard block only if conditions are mature enough.

### Recommended safe policy

#### Phase 1 (live)
Sizing only:
- VERY_WEAK -> 0.30x
- WEAK -> 0.60x
- GOOD -> 0.85x
- EXCELLENT -> 1.00x

#### Phase 2 (later)
Hard block only if all hold:
- `n >= 12`
- `conv >= minimum`
- `ev <= 0`
- recent window confirms underperformance

### Pseudocode

```python
mult = get_cell_quality_multiplier(sym, regime, state=lm_state)
size *= mult

if ENABLE_HARD_CELL_BLOCK:
    if should_block_cell(sym, regime, state=lm_state):
        return reject("CELL_QUALITY_BLOCK")
```

### Important note
Do not hard-block immature cells based only on low WR with tiny sample.

### Acceptance criteria

- BNB/BEAR and DOT/BEAR stop consuming normal size
- portfolio capital shifts away from persistent losers
- aggregate WR/PF not dragged by obviously weak cells

---

## 8. Exit monetization integration

### Objective
Convert excessive scratch-dominant behavior into actual monetization of good trades.

### Files to update

- `smart_exit_engine.py`
- `trade_executor.py`
- entry metadata / position state

### Required behavior
At entry, generate exit plan from `exit_monetization`:

- TP1 / TP2 ladder
- scratch activation age
- regime-aware stagnation timeout

### Critical rollout rule
This module must support **shadow mode first**.

In shadow mode, log:
- what TP1/TP2 would have been
- what scratch age would have been
- whether shadow exit would outperform live exit

### Suggested rollout sequence

#### Step 1 — shadow only
No live behavior changes.

#### Step 2 — live TP1 only
Keep rest of legacy exit logic.

#### Step 3 — TP1 + TP2

#### Step 4 — scratch activation age

#### Step 5 — regime-aware stagnation timeout

### Why staged?
Because exit logic is the most likely place to accidentally:
- cut winners too early
- increase hold time without payoff
- hide losses behind prettier metrics

### Acceptance criteria

- scratch share declines materially
- partial TP volume rises
- PF improves without large drawdown spike
- average realized winner size increases

---

## 9. Probability calibration integration

### Objective
Map raw `p` to empirical reliability before EV calculation.

### Files to update

- `realtime_decision_engine.py`
- signal generation / score computation path
- post-trade recorder

### Safe rollout rule
Start in **shadow mode only**.

### Shadow mode requirements
Log:
- raw probability
- calibrated probability
- EV(raw)
- EV(calibrated)
- whether final decision would change

Example:

```text
[CALIB_SHADOW] raw_p=0.46 calib_p=0.58 ev_raw=0.008 ev_cal=0.021 decision_live=SKIP decision_shadow=TAKE
```

### Data-quality guardrails
Do not recalibrate buckets aggressively on tiny sample.

Recommended:
- bucket minimum > 10 if possible
- prefer 25+ for reliable live effect
- use fallback to raw probability if insufficient bucket support

### Mandatory rule
Calibration happens **before EV calculation**, not after.

### Acceptance criteria

- raw vs calibrated p is visible and auditable
- bucket instability is controlled
- no silent live decision shift without logs

---

## 10. Feature pruning integration

### Objective
Reduce influence of persistently weak features while preserving combinational signal diversity.

### Files to update

- feature extraction / signal scoring layer
- `signal_engine.py` or `realtime_decision_engine.py`

### Safe rollout rule
Also start in **shadow mode only**.

### Recommendation
Use softer initial multipliers than the raw module defaults if needed.

Suggested first live rollout:
- EXCELLENT -> 1.20x
- GOOD -> 1.05x
- BASELINE -> 1.00x
- WEAK -> 0.80x
- VERY_WEAK -> 0.50x

Only later tighten to `0.30x` for proven bad features.

### Reason
A feature can be weak standalone but useful in interaction. Over-pruning too early can reduce model breadth.

### Shadow logging example

```text
[FEATURE_SHADOW] feature=breakout base=1.00 adj=0.50 winrate=0.43 sample=214
```

### Acceptance criteria

- feature quality table visible in monitoring
- weak features are downweighted gradually
- no abrupt collapse in signal breadth

---

## 11. Correct decision pipeline ordering

This ordering should be enforced explicitly to avoid hidden contradictions:

1. market / feature extraction
2. optional feature weighting (shadow or live)
3. raw probability generation
4. probability calibration (shadow or live)
5. EV calculation
6. hard EV-only rejection
7. bootstrap state evaluation
8. score / threshold gating with allowed relaxation
9. cell quality multiplier / optional block
10. execution quality / net edge / cost checks
11. final position sizing
12. exit monetization plan generation
13. audit tracking

### Non-negotiable rule
Nothing after step 6 may resurrect a negative-EV trade.

---

## 12. Suggested code patterns

### A. Decision context container

Create or extend a context object passed through the decision pipeline.

```python
@dataclass
class DecisionContext:
    sym: str
    regime: str
    branch: str
    raw_p: float
    calibrated_p: float
    ev_raw: float
    ev_final: float
    score: float
    bootstrap_state: str
    bootstrap_size_mult: float
    bootstrap_gate_mult: float
    cell_quality_mult: float
    feature_adjustments: dict
    exit_plan: dict
    gate_failed: str | None = None
    decision: str | None = None
```

This makes logs and audits much cleaner.

### B. One final decision logger

Prefer one canonical logger call rather than scattered prints:

```python
def log_final_decision(ctx: DecisionContext):
    ...
```

### C. One final metrics source

Never compute PF/WR ad hoc in downstream UI or audit code.

---

## 13. Tests required before production enablement

### Unit tests

Must add tests for:

- canonical metric equivalence on known trade sets
- bootstrap transitions
- cell multiplier tiers
- exit ladder generation
- scratch activation timing
- probability bucket mapping
- feature weight updates
- regression detection rules

### Integration tests

Need replay/sim tests for:

- current baseline logs
- weak-cell scenarios
- negative EV rejection preserved
- audit summary generation
- shadow/live mode differences

### Production-safety tests

Before enabling each module live, verify:

- no exception path under empty/partial learning state
- no NaN / inf propagation
- no new high-frequency logging explosion
- no Firestore write/read budget blow-up

---

## 14. Rollout checklist

### Release 1
- canonical metrics live
- audit enhancements live
- audit regression testing warn-only

### Release 2
- bootstrap sizing live
- bootstrap gate relaxation live
- cell quality sizing live

### Release 3
- exit monetization shadow

### Release 4
- TP1 live

### Release 5
- TP2 + scratch delay live

### Release 6
- probability calibration shadow
- feature pruning shadow

### Release 7
- probability calibration live for mature buckets only

### Release 8
- feature pruning live, soft multipliers only

---

## 15. What success should look like

Do **not** focus only on PF. Use a multi-metric success definition.

### Primary success metrics

- canonical PF rises from current baseline
- scratch share declines materially
- partial TP share rises
- negative EV leakage stays at zero
- audit acceptance remains stable or improves

### Secondary success metrics

- fewer weak cells consuming capital
- better branch-level audit clarity
- fewer unexplained decision contradictions
- better agreement between raw p, calibrated p, and realized outcomes over time

### Failure signals

Rollback or disable recent module if any of these happen:

- PF drops materially for 50–100 trade window
- drawdown spikes sharply
- accepted weak EV trades increase
- signal breadth collapses
- branch pass rate collapses
- audit blocker shifts to a clearly broken gate after new integration

---

## 16. Implementation priorities for Claude/Codex

### Highest priority now

1. wire `canonical_metrics` everywhere
2. wire `audit_enhancements` into decision path
3. wire `audit_regression_testing` into pre-live audit
4. add feature flags + shadow infrastructure

### Second priority

5. integrate `bootstrap_state_machine` into sizing and gate relaxation
6. integrate `cell_quality_penalty` into final size

### Third priority

7. integrate `exit_monetization` in shadow mode only

### Last priority

8. integrate `probability_calibration` and `feature_pruning` in shadow mode

---

## 17. Direct implementation instructions

Implement incrementally. After each step:

1. run unit tests
2. run replay/pre-live audit
3. compare canonical metrics snapshot
4. compare audit regression report
5. verify logs are readable and not contradictory

Do not batch all changes into one giant patch.

For each integration patch, produce:

- files changed
- exact functions modified
- why the change is safe
- before/after log examples
- rollback instructions

---

## 18. Final recommendation

This integration should be treated as a **controlled economics migration**, not a normal patch.

The biggest immediate wins are likely:

- canonical metrics unification
- audit observability
- bootstrap-aware sizing
- cell quality penalties
- exit monetization

The biggest overfitting risks are likely:

- probability calibration too early
- feature pruning too aggressively
- hard cell blocking on immature samples

Therefore:

- integrate metrics and audit first
- integrate sizing controls second
- integrate exits third
- integrate calibration/pruning last
