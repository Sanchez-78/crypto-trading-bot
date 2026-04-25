# CryptoMaster — Addendum k novým logům (2026-04-25)

## Hlavní závěr
Nové logy ukazují, že poslední patch posunul systém správným směrem v bezpečnosti, ale vznikly 2 nové kritické regresní chyby:

1. **Canonical state stále neřídí maturity**
2. **Economic gate je přestřelený a blokuje skoro celý engine**

---

## 1) Canonical state stále neřídí maturity

Z logu:
```text
effective_completed_trades=100 (from learning state)
Maturity computed: trades=0 bootstrap=True cold_start=True
```

To znamená, že po validaci stale globálů se sice state opraví, ale `unified maturity` stále nečte `canonical_state.logic_completed_trades`.

### Dopad
- false cold-start
- false bootstrap mode
- zbytečně aktivní reduced sizing
- zkreslené další ochrany

### Oprava
```python
def get_maturity_trade_count(metrics: dict) -> int:
    canonical = metrics.get("canonical_state", {})
    logic_trades = canonical.get("logic_completed_trades")
    if logic_trades is not None:
        return int(logic_trades)
    return int(metrics.get("completed_trades_runtime", 0))
```

```python
def compute_unified_maturity(metrics: dict, learning_state: dict) -> dict:
    trades = get_maturity_trade_count(metrics)
    min_pair_n = learning_state.get("min_pair_n", 0)
    converged_pairs = learning_state.get("converged_pairs", 0)
    breadth_pairs = learning_state.get("breadth_pairs", 0)

    bootstrap = (
        trades < 150
        or min_pair_n < 15
        or converged_pairs < 4
        or breadth_pairs < 6
    )

    return {
        "completed_trades": trades,
        "bootstrap": bootstrap,
        "cold_start": trades < 50,
    }
```

---

## 2) Economic gate je teď příliš agresivní

Z logu:
```text
decision=SKIP_ECONOMIC [ECONOMIC_GATE] Recent performance degrading (0.0% vs 51.5%)
Passed to execution    : 0
Blocked                : 20
[CI FAIL] blocked_ratio=1.000 > 0.80
```

To velmi pravděpodobně znamená:
- recent sample po restartu je prázdný nebo nedostatečný,
- fallback vrátí `0.0%`,
- gate to interpretuje jako skutečný propad výkonnosti,
- a zablokuje prakticky vše.

### To je chyba
Prázdný nebo malý recent sample nesmí být interpretován jako reálné zhoršení.

### Oprava
```python
def compute_recent_wr(trades, window=24):
    sample = trades[-window:] if len(trades) >= window else []
    decisive = [t for t in sample if t.get("result") in ("WIN", "LOSS")]

    if len(decisive) < 8:
        return None, len(decisive)

    wins = sum(1 for t in decisive if t["result"] == "WIN")
    return wins / len(decisive), len(decisive)
```

```python
def economic_gate_decision(stats: dict) -> dict:
    recent_wr = stats.get("recent_wr")
    recent_n = stats.get("recent_n", 0)
    baseline_wr = stats.get("baseline_wr", 0.0)

    if recent_wr is None or recent_n < 8:
        return {
            "mode": "INSUFFICIENT_RECENT_DATA",
            "block": False,
            "size_mult": 0.90,
            "reason": f"recent sample too small (n={recent_n})"
        }

    delta = recent_wr - baseline_wr

    if delta < -0.10:
        return {"mode": "DEGRADED", "block": False, "size_mult": 0.70, "reason": f"recent delta={delta:.3f}"}
    if delta < -0.05:
        return {"mode": "CAUTION", "block": False, "size_mult": 0.85, "reason": f"recent delta={delta:.3f}"}
    return {"mode": "NORMAL", "block": False, "size_mult": 1.00, "reason": "stable"}
```

---

## 3) Economic gate nesmí být CI blocker

Teď audit failuje hlavně kvůli tomu, že economic gate blokuje celý replay flow.

To je špatně.

### Pravidlo
- `pre_live_audit` má testovat mechanickou konzistenci
- economic protection v auditu má být maximálně telemetry nebo soft scaling
- nemá shazovat CI

### Oprava
```python
if context.mode == "audit":
    economic_block_allowed = False
else:
    economic_block_allowed = True
```

Ještě lepší varianta:
```python
if context.mode == "audit":
    eco_action = "annotate_only"
elif context.mode == "live":
    eco_action = "soft_scale"
```

---

## 4) Profit Factor source je nekonzistentní

Log ukazuje:

```text
Economic: 0.467 [FRAGILE]
PF: 4.15
```

ale dashboard současně ukazuje:

```text
Profit Factor 0.65x
```

To je zásadní nekonzistence.

### Oprava
Jeden kanonický PF výpočet pro:
- dashboard
- economic gate
- audit
- health

```python
def canonical_profit_factor(closed_trades: list[dict]) -> float:
    gross_win = sum(max(t.get("net_pnl", 0.0), 0.0) for t in closed_trades)
    gross_loss = sum(abs(min(t.get("net_pnl", 0.0), 0.0)) for t in closed_trades)

    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss
```

Přidej i audit log:
```python
log.info(
    "[PF_CANONICAL] gross_win=%.8f gross_loss=%.8f pf=%.4f",
    gross_win, gross_loss, pf
)
```

---

## 5) Forced explore gate je dobrý, ale pořadí gate není ideální

Pozitivní zpráva:
- forced explore gate teď opravdu filtruje nekvalitní forced vstupy
- spread gate blokuje slabé signály

To je správně.

Ale logika priority gate by měla být čistší.

### Doporučené pořadí
1. invalid state / canonical mismatch
2. hard market invalidators
3. EV hard gate
4. execution quality hard gate
5. economic soft gate
6. forced explore gate
7. score gate
8. size/risk modifiers

### Pravidlo
Po prvním definitivním blockeru už další decisional gates nelogovat jako hlavní reason.

---

## 6) Co je naopak lepší než dřív

Navzdory regresi je tu i pokrok:

- forced explore už není tak volný
- spread/quality protection funguje
- harvest rate se zvedl z cca `4.9%` na `11.7%`
- systém je bezpečnější proti špatným forced obchodům
- scratch je stále vysoký, ale směr je lepší než předtím

To znamená:
**nové ochrany nejsou špatný nápad, jen jsou teď moc tvrdé a aktivují se ve špatný čas.**

---

## 7) Doporučené pořadí patchů

### PATCH 1
Opravit `unified maturity`, aby používal canonical trades = **100**, ne **0**.

### PATCH 2
Economic gate:
- nesmí používat prázdný recent sample jako `0.0%`
- při malém sample má vracet `INSUFFICIENT_RECENT_DATA`
- má primárně škálovat, ne blokovat

### PATCH 3
Vyjmout economic gate z CI fail logiky.

### PATCH 4
Sjednotit PF source.

### PATCH 5
Přepnout economic policy z `block-first` na `scale-first`.

---

## 8) Nejkratší praktický závěr

Aktuální problém už není:
- „bot dělá moc špatných vstupů“

Aktuální problém je:
- **„bot se po startu vyhodnotí jako cold/degraded a skoro nic nepustí“**

### Dvě nejdůležitější opravy
1. `maturity trades=100`, ne `0`
2. economic gate nesmí brát prázdný recent sample jako skutečný propad výkonu

Bez těchto dvou oprav bude bot po restartu systematicky padat do:
- false cold-start,
- false degraded mode,
- false CI fail,
- nulové exekuce.
