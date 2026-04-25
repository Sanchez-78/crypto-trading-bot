# CryptoMaster — doporučení z aktuálních logů

## Shrnutí
Bot už nepůsobí jako čistě rozbitý při startu. Hlavní problém se přesunul z bootstrap/startup nekonzistence do **ekonomiky obchodování**:

- bot otevře obchody,
- winrate vypadá na první pohled dobře,
- ale **closed PnL zůstává záporné**,
- **profit factor je nízký**,
- a dominují **SCRATCH_EXIT**.

To znamená, že systém má nějaký edge na úrovni selekce, ale **nedokáže ho dostatečně monetizovat**.

---

## Priorita 1 — opravit startup source of truth
V logu je opakovaně vidět:

- načte se stale global state,
- bot ho detekuje až následně,
- pak teprve provede cleanup.

To je lepší než dřív, ale stále je to jen obranná oprava.

### Doporučení
Přesunout cleanup a inicializaci tak, aby stale globální stav vůbec nebyl použit pro logiku.

### Cíl
Mít při startu jen tyto autoritativní zdroje:

- `runtime_canonical_trades`
- `bootstrap_historical_trades`
- `dashboard_reconciled_trades`

### Pravidla
- logika nesmí číst staré globální počty obchodů,
- dashboard může mít vlastní reconciled count,
- bootstrap count nesmí přepsat runtime logic count.

### Proč
Dokud stale state existuje a až následně se maže, je tu riziko:
- špatného maturity modu,
- špatného risk modu,
- zavádějící diagnostiky,
- budoucích side effect bugů.

---

## Priorita 2 — hluboká forenzní analýza `SCRATCH_EXIT`
Tohle je teď největší ekonomický problém.

### Co je vidět
- winrate je relativně vysoké,
- PF je nízký,
- closed PnL je záporné,
- scratch exit tvoří drtivou většinu uzavření.

To znamená, že obchody často:
- nejdou dostatečně rychle do zisku,
- nebo jdou do lehkého plusu, ale zisk se nezmonetizuje,
- nebo fee a mikro-ztráty rozežerou celý edge.

### Nutné doplnit do logů pro každý scratch
- `mfe`
- `mae`
- `hold_time_sec`
- `max_unrealized_pnl`
- `best_rr_reached`
- `did_touch_partial25`
- `did_touch_micro_tp`
- `fee_only_loss`
- `scratch_reason`

### Scratch klasifikace
Rozdělit scratch na:
- `GOOD_DEFENSIVE_SCRATCH`
- `NEUTRAL_SCRATCH`
- `LOSSY_PREMATURE_SCRATCH`

### Proč
Bez této klasifikace bude další ladění výstupů naslepo.

---

## Priorita 3 — oddělit `model health` od `economic health`
V logu se objevuje stav `GOOD`, ale zároveň:

- trend učení se zhoršuje,
- PF < 1,
- closed PnL < 0,
- edge je slabý,
- convergence je nízká,
- breadth je slabý.

To je zavádějící.

### Doporučení
Rozdělit zdraví na tři samostatné vrstvy:

- `model_health`
- `economic_health`
- `execution_health`

A z nich vypočítat finální label:

- `GOOD`
- `CAUTION`
- `FRAGILE`
- `DEGRADED`

### Praktická interpretace pro současný stav
Současný stav je spíš:

**FRAGILE**

než `GOOD`.

---

## Priorita 4 — zpřísnit bootstrap režim
Bot po resetu načte omezený runtime základ a poměrně rychle začne otevírat více pozic.

To je funkční, ale ekonomicky riskantní.

### Doporučení
Dokud platí aspoň jedna z podmínek:

- `min_pair_n < 15`
- `converged_pairs < target`
- `breadth < threshold`

tak:

- snížit `max_positions`,
- snížit risk budget,
- snížit agresivitu `FORCED_EXPLORE`,
- omezit simultánní entry v jednom cyklu,
- držet mírnější sizing.

### Smysl
Bootstrap nemá být „plně agresivní live“, ale **řízený měkký start**.

---

## Priorita 5 — harvest a near-miss tuning
Velmi důležitý signál z logu:

- `partial25_near_miss`
- `micro_near_miss`

To znamená, že významná část obchodů byla blízko monetizace, ale systém ji neuzamkl.

### Doporučení
Přidat metriky:

- kolik scratch obchodů mělo kladný MFE nad fee,
- kolik se dostalo těsně pod partial threshold,
- kolik obchodů bylo v plusu a pak skončilo scratch/loss,
- kolik scratchů bylo pouze fee-drag.

### Následné experimenty
- dřívější micro TP,
- fee-aware early harvest,
- nižší partial threshold v některých režimech,
- time-based harvest po krátké pozitivní excursion,
- jemnější scratch-to-micro conversion.

### Proč
Tohle má nejspíš vyšší ROI než další honění winrate.

---

## Priorita 6 — omezit `FORCED_EXPLORE`
V logu je stále vidět forced explore a forced signals.

To může být v bootstrapu užitečné, ale pokud:
- edge je slabý,
- scratch rate je extrémní,
- convergence je nízká,

tak forced explore může víc škodit než pomáhat.

### Doporučení
Povolit forced explore jen když současně platí:

- spread OK,
- exec quality OK,
- OFI toxicity nízká,
- coherence nad minimem,
- pair není ve weak-edge bucketu,
- pair není v loss cluster režimu,
- bootstrap risk mode dovoluje exploraci.

---

## Priorita 7 — přidat `economic gate`
Vedle EV/score/coherence gate chybí vyšší ekonomická vrstva.

### Doporučení
Pokud za posledních N obchodů:

- `profit_factor < threshold`
- `scratch_rate > threshold`
- `partial_capture_rate < threshold`
- `recent_performance_trend` klesá

pak automaticky:

- snížit sizing,
- snížit max positions,
- omezit forced explore,
- zpřísnit vstupy do slabých setupů.

### Smysl
Bot by neměl obchodovat stejnou intenzitou v období, kdy ekonomika obchodování evidentně degraduje.

---

## Priorita 8 — explicitní startup report
Po startu chybí jeden stručný blok, který jasně popíše, z čeho systém právě žije.

### Doporučený výstup
```text
[STARTUP_CANONICAL]
historical_bootstrap_trades=...
runtime_logic_trades=...
dashboard_trades=...
stale_globals_detected=True/False
stale_globals_cleared=True/False
logic_source=runtime
dashboard_source=reconciled_500
maturity=bootstrap/live
risk_mode=reduced/normal
```

### Proč
Tohle dramaticky zrychlí troubleshooting.

---

## Co bych implementoval jako první
1. startup source-of-truth cleanup
2. scratch exit forensics
3. health relabel + economic health
4. bootstrap risk reduction
5. harvest tuning podle near-miss dat
6. forced-explore quality gate
7. economic gate

---

## Největší závěr
Hlavní problém už není jen „startup nekonzistence“.

Hlavní problém je teď:

**bot obchoduje, ale neumí dostatečně monetizovat edge.**

Tedy:
- selekce není úplně mrtvá,
- ale exit/harvest ekonomika je slabá,
- scratch dominance a fee drag stále zabíjejí výkon.

---

## Doporučení pro další patch
Další patch by měl být zaměřený primárně na:

- `SCRATCH_EXIT` diagnostiku,
- harvest/near-miss monetizaci,
- oddělení model vs economic health,
- bezpečnější bootstrap režim.

To má nejvyšší praktický dopad.


---

# Návrhy logiky a kódu

## 1) Startup source of truth — návrh logiky

### Cíl
Zajistit, aby po startu nikdy nedošlo k použití stale globálních metrik pro rozhodování.

### Logika
Pořadí inicializace musí být:

1. načti Redis/Firebase bootstrap data,
2. sestav `canonical_runtime_state`,
3. explicitně vynuluj / odpoj legacy globální metriky,
4. až potom dovol:
   - výpočet maturity,
   - audit,
   - sizing,
   - první signály.

### Doporučená pravidla
- `logic_state.completed_trades` musí být jediný zdroj pro RDE/maturity/risk.
- `dashboard_state.completed_trades` může být oddělený, ale pouze pro UI.
- `bootstrap_state.completed_trades` slouží jen pro historickou informaci a kalibraci.

### Návrh kódu
```python
def build_canonical_runtime_state(redis_state, firebase_history, model_state):
    runtime_trades = extract_runtime_trade_count(redis_state, model_state)
    bootstrap_trades = len(firebase_history or [])
    dashboard_trades = min(500, bootstrap_trades) if bootstrap_trades else runtime_trades

    return {
        "logic_completed_trades": runtime_trades,
        "bootstrap_completed_trades": bootstrap_trades,
        "dashboard_completed_trades": dashboard_trades,
        "state_source": "runtime",
    }


def clear_legacy_global_metrics(metrics: dict) -> None:
    keys = [
        "completed_trades",
        "win_count",
        "loss_count",
        "flat_count",
        "trade_history_count",
    ]
    for k in keys:
        metrics[k] = 0


def init_runtime_state(redis_state, firebase_history, model_state, metrics):
    canonical = build_canonical_runtime_state(redis_state, firebase_history, model_state)
    clear_legacy_global_metrics(metrics)
    metrics["canonical_state"] = canonical
    metrics["completed_trades_runtime"] = canonical["logic_completed_trades"]
    return canonical
```

### Guard
```python
def get_logic_completed_trades(metrics: dict) -> int:
    canonical = metrics.get("canonical_state", {})
    return int(canonical.get("logic_completed_trades", 0))
```

---

## 2) SCRATCH_EXIT forensics — návrh logiky

### Cíl
Rozlišit, které scratch exity:
- chrání kapitál,
- jsou neutrální,
- a které ničí edge předčasně.

### Co ukládat do pozice během života obchodu
```python
pos["mfe"] = max(pos.get("mfe", float("-inf")), unrealized_pnl)
pos["mae"] = min(pos.get("mae", float("inf")), unrealized_pnl)
pos["best_rr"] = max(pos.get("best_rr", 0.0), current_rr)
pos["held_sec"] = int(now_ts - pos["opened_ts"])
pos["touched_micro"] = pos.get("touched_micro", False) or (unrealized_pnl >= micro_tp_level)
pos["touched_partial25"] = pos.get("touched_partial25", False) or (unrealized_pnl >= partial25_level)
```

### Scratch klasifikace
```python
def classify_scratch_exit(pos, fee_rt: float) -> str:
    mfe = pos.get("mfe", 0.0)
    held = pos.get("held_sec", 0)
    touched_micro = pos.get("touched_micro", False)
    touched_partial = pos.get("touched_partial25", False)

    fee_drag = 2.0 * fee_rt

    if touched_partial or mfe > 2.0 * fee_drag:
        return "LOSSY_PREMATURE_SCRATCH"
    if mfe > fee_drag or held > 180:
        return "NEUTRAL_SCRATCH"
    return "GOOD_DEFENSIVE_SCRATCH"
```

### Uložení do statistik
```python
def record_scratch_forensics(metrics: dict, pos: dict, fee_rt: float) -> None:
    cls = classify_scratch_exit(pos, fee_rt)
    bucket = metrics.setdefault("scratch_forensics", {
        "GOOD_DEFENSIVE_SCRATCH": 0,
        "NEUTRAL_SCRATCH": 0,
        "LOSSY_PREMATURE_SCRATCH": 0,
    })
    bucket[cls] += 1
```

---

## 3) Harvest tuning — návrh logiky

### Problém
Mnoho obchodů je v logu jako near miss:
- `partial25_near_miss`
- `micro_near_miss`

To naznačuje, že harvest threshold může být příliš pozdě.

### Doporučená logika
Použít měkkou monetizaci podle MFE a času v trhu.

```python
def should_take_micro_harvest(pos: dict, fee_rt: float, regime: str) -> bool:
    pnl = pos.get("unrealized_pnl", 0.0)
    mfe = pos.get("mfe", 0.0)
    held = pos.get("held_sec", 0)

    fee_drag = 2.0 * fee_rt
    min_lock = fee_drag * 1.35

    if pnl < min_lock:
        return False

    if regime in {"RANGING", "QUIET_RANGE"} and held >= 45:
        return True
    if mfe > min_lock * 1.8 and pnl < mfe * 0.55:
        return True
    if held >= 120 and pnl > min_lock:
        return True
    return False
```

### Důvod
Když obchod ukázal kladný excursion, ale vrací se, systém má zamknout aspoň malou část edge místo pozdějšího scratch.

---

## 4) Economic health — návrh logiky

### Problém
Současné `GOOD` nereflektuje ekonomickou realitu.

### Návrh výpočtu
```python
def compute_economic_health(stats: dict) -> dict:
    pf = float(stats.get("profit_factor", 0.0))
    scratch_rate = float(stats.get("scratch_rate", 1.0))
    recent_wr_delta = float(stats.get("recent_wr_delta", 0.0))
    partial_capture_rate = float(stats.get("partial_capture_rate", 0.0))

    score = 1.0

    if pf < 1.0:
        score -= 0.35
    if scratch_rate > 0.70:
        score -= 0.25
    if recent_wr_delta < -0.05:
        score -= 0.20
    if partial_capture_rate < 0.08:
        score -= 0.20

    score = max(0.0, min(1.0, score))

    if score >= 0.75:
        label = "GOOD"
    elif score >= 0.55:
        label = "CAUTION"
    elif score >= 0.35:
        label = "FRAGILE"
    else:
        label = "DEGRADED"

    return {"score": score, "label": label}
```

### Doporučené zobrazení
- `model_health`
- `economic_health`
- `execution_health`
- `final_health`

```python
def combine_health(model_h, economic_h, execution_h):
    score = 0.35 * model_h + 0.45 * economic_h + 0.20 * execution_h
    if score >= 0.75:
        return "GOOD", score
    if score >= 0.55:
        return "CAUTION", score
    if score >= 0.35:
        return "FRAGILE", score
    return "DEGRADED", score
```

---

## 5) Bootstrap risk mode — návrh logiky

### Cíl
V bootstrapu nesmí bot otevírat plnou agresi.

```python
def compute_bootstrap_risk_mode(state: dict) -> dict:
    min_pair_n = state.get("min_pair_n", 0)
    converged_pairs = state.get("converged_pairs", 0)
    breadth_pairs = state.get("breadth_pairs", 0)
    completed_trades = state.get("completed_trades", 0)

    bootstrap_active = (
        min_pair_n < 15
        or converged_pairs < 4
        or breadth_pairs < 6
        or completed_trades < 150
    )

    if bootstrap_active:
        return {
            "mode": "BOOTSTRAP_REDUCED",
            "max_positions": 2,
            "risk_budget_mult": 0.55,
            "size_mult": 0.65,
            "forced_explore_mult": 0.40,
        }

    return {
        "mode": "NORMAL",
        "max_positions": 3,
        "risk_budget_mult": 1.00,
        "size_mult": 1.00,
        "forced_explore_mult": 1.00,
    }
```

### Integrace
```python
risk_mode = compute_bootstrap_risk_mode(runtime_state)

final_size *= risk_mode["size_mult"]
risk_budget *= risk_mode["risk_budget_mult"]
max_positions = min(max_positions, risk_mode["max_positions"])
forced_explore_weight *= risk_mode["forced_explore_mult"]
```

---

## 6) Forced explore quality gate — návrh logiky

### Problém
Forced explore má být nouzová explorace, ne bypass kvality.

```python
def forced_explore_allowed(ctx: dict) -> bool:
    if ctx["spread"] > ctx["spread_limit"]:
        return False
    if ctx["exec_quality"] < 0.62:
        return False
    if ctx["ofi_toxicity"] > ctx["ofi_limit"]:
        return False
    if ctx["coherence"] < 0.55:
        return False
    if ctx["in_loss_cluster"]:
        return False
    if ctx["edge_bucket"] == "weak":
        return False
    if ctx["bootstrap_mode"] == "BOOTSTRAP_REDUCED" and ctx["forced_explore_budget"] <= 0:
        return False
    return True
```

### Výsledek
Forced signál vznikne jen tehdy, když tržní a mikrostrukturní podmínky dávají alespoň smysl.

---

## 7) Economic gate — návrh logiky

### Cíl
Když ekonomika degradovala, systém musí sám ubrat agresi.

```python
def compute_economic_gate(stats: dict) -> dict:
    pf = stats.get("profit_factor", 0.0)
    scratch_rate = stats.get("scratch_rate", 1.0)
    partial_capture = stats.get("partial_capture_rate", 0.0)
    recent_trend = stats.get("recent_wr_delta", 0.0)

    if pf < 0.9 and scratch_rate > 0.75:
        return {"mode": "DEFENSIVE", "size_mult": 0.60, "max_positions": 1, "explore_mult": 0.25}
    if pf < 1.0 or recent_trend < -0.05:
        return {"mode": "CAUTION", "size_mult": 0.80, "max_positions": 2, "explore_mult": 0.50}
    if partial_capture < 0.08 and scratch_rate > 0.65:
        return {"mode": "HARVEST_PRESSURE", "size_mult": 0.85, "max_positions": 2, "explore_mult": 0.60}
    return {"mode": "NORMAL", "size_mult": 1.00, "max_positions": 3, "explore_mult": 1.00}
```

### Použití
```python
eco_gate = compute_economic_gate(economic_stats)
final_size *= eco_gate["size_mult"]
max_positions = min(max_positions, eco_gate["max_positions"])
forced_explore_weight *= eco_gate["explore_mult"]
```

---

## 8) Doplnění dashboard logiky

### Doporučení
Do dashboardu přidat nové metriky:

- `scratch_good_defensive`
- `scratch_neutral`
- `scratch_lossy_premature`
- `partial_capture_rate`
- `micro_capture_rate`
- `fee_drag_rate`
- `economic_health_label`
- `bootstrap_risk_mode`
- `forced_explore_accept_rate`

### Příklad serializace
```python
dashboard["economic"] = {
    "profit_factor": stats["profit_factor"],
    "scratch_rate": stats["scratch_rate"],
    "partial_capture_rate": stats["partial_capture_rate"],
    "economic_health": eco_health["label"],
    "economic_score": round(eco_health["score"], 3),
}

dashboard["scratch_forensics"] = metrics.get("scratch_forensics", {})
dashboard["risk_mode"] = risk_mode["mode"]
dashboard["economic_gate"] = eco_gate["mode"]
```

---

## 9) Co implementovat hned
Nejvyšší ROI má tento balík:

### Patch A
- canonical startup state
- zákaz použití stale globals pro logiku

### Patch B
- scratch forensics
- klasifikace scratch exitů
- near-miss metriky

### Patch C
- economic health
- economic gate
- bootstrap reduced mode

### Patch D
- forced explore quality gate
- dřívější micro/partial monetizace

---

## 10) Nejkratší praktický závěr
Bot teď nepotřebuje primárně další “smart vstupy”.

Bot teď potřebuje hlavně:

1. **čistý canonical runtime state**
2. **forenzní diagnostiku scratch exitů**
3. **lepší monetizaci pozitivního excursion**
4. **economic/risk throttling při degradaci**

To je nejpravděpodobnější cesta, jak z vysokého WR přestat dělat záporný closed PnL.
