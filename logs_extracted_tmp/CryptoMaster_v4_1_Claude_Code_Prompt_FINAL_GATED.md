# CryptoMaster v4.1 — FINAL Claude Code Prompt (GATED)
## Runtime Isolation Acceptance + opravená budoucí PAPER roadmapa

**Version:** 4.1-GATED  
**Datum:** 2026-05-25  
**Projekt:** `CryptoMaster_srv` · Binance USDⓈ-M Perpetual Futures · Python event-driven bot  
**Mode:** PAPER only. REAL trading je zakázán, dokud neexistuje samostatné explicitní lidské rozhodnutí.  
**Poslední hlášený stav — MUSÍ BÝT OVĚŘEN, NESMÍ BÝT PŘEDPOKLÁDÁN:** service stopped; expected production HEAD `791d16c`; review candidate `b6311c2`; `data/paper_open_positions.json` clean/empty; active `server_local_backups/paper_adaptive_learning_state.json` absent.

---

# MASTER DECISION

## Jediný aktivní úkol v této session

Proveď pouze:

1. **Phase 0A — Runtime/Test Isolation Acceptance** candidate `b6311c2` proti očekávanému baseline `791d16c`.
2. **Phase 0B — Read-only Binance Runtime Compatibility Inventory.**

Nevykonávej Phase 1 ani žádnou pozdější implementaci. Nesmíš změnit kód, commitovat, deployovat, aktualizovat runtime working tree ani spustit/zastavit/restartovat službu.

## Proč V4.1 nahrazuje V4.0

| Chyba/riziko V4.0 | Oprava V4.1 |
|---|---|
| Hardcoded HEAD/candidate jako jistota | Pouze poslední hlášený baseline; musí být znovu ověřen |
| Phase 0 směšovala acceptance s budoucími změnami | Phase 0 je výhradně read-only audit + izolované testy |
| Hash check používal `|| echo FAIL` bez skutečného ukončení | Při mutaci manifestu musí audit skončit non-zero |
| Hlídány jen dva známé soubory | Skenuj writery a porovnávej manifest všech nalezených state cest |
| Depth stream uveden pod `/market` | Depth a `bookTicker` jsou `/public` |
| RPI názvy byly chybné | Správně: `<symbol>@rpiDepth@500ms`, `GET /fapi/v1/rpiDepth` |
| ADL použilo `adlQuantile 0–4` a vymyšlený close model | Ověřený symbol monitoring: `/fapi/v1/symbolAdlRisk`, hodnoty `low/medium/high`; jen telemetry |
| VPIN z `aggTrade.nq` navržen rovnou do policy | `q`/`nq` pouze capture; VPIN až samostatný offline research |
| DSR pseudo-kód byl matematicky chybný | Žádná vlastní implementace bez golden tests proti publikované metodice |
| PBO/CSCV zaměněno za test forward PAPER streamu | Používat jen pro offline matici variant na společném replay datasetu |

---

# ABSOLUTNÍ INVARIANTY

```text
I01 REAL/live trading nikdy automaticky nepovolit.
I02 V aktuální session neprovést žádnou změnu zdrojového kódu.
I03 V aktuální session neprovést commit/merge/pull/deploy ani systemd action.
I04 Pokud je service aktivní, nespouštět testy a reportovat blocker; službu automaticky nezastavovat.
I05 Candidate testy běží jen v izolované kopii mimo runtime working tree.
I06 Testy nesmějí vytvořit ani změnit production ani candidate-relative runtime state.
I07 Pokud expected baseline HEAD nesouhlasí s observed HEAD, nevydávat acceptance PASS.
I08 Pokud candidate není dostupný lokálně, nefetchovat automaticky; reportovat blocker.
I09 PASS isolation neznamená restart, pokud runtime-used Binance WS cesta používá legacy URL.
I10 Žádná Phase 1+ práce v této session, ani pokud Phase 0 projde.
```

---

# PHASE 0A — RUNTIME / TEST ISOLATION ACCEPTANCE
## ACTIVE NOW

## Task A1 — Read-only discovery skutečného runtime stavu

```bash
set -euo pipefail

EXPECTED_PROD_HEAD="791d16c"
EXPECTED_CANDIDATE="b6311c2"

for d in /opt/cryptomaster /opt/CryptoMaster_srv "$HOME/CryptoMaster_srv"; do
  if [ -d "$d/.git" ]; then RUNTIME_REPO="$d"; break; fi
done
: "${RUNTIME_REPO:?FAIL: runtime repository not found}"

cd "$RUNTIME_REPO"
OBSERVED_HEAD="$(git rev-parse HEAD)"
echo "RUNTIME_REPO=$RUNTIME_REPO"
echo "EXPECTED_PROD_HEAD=$EXPECTED_PROD_HEAD"
echo "OBSERVED_HEAD=$OBSERVED_HEAD"
git status --short --untracked-files=all
git log --oneline -10

SERVICE_STATE="$(systemctl is-active cryptomaster.service 2>/dev/null || true)"
echo "cryptomaster.service=$SERVICE_STATE"

if [ "$SERVICE_STATE" = "active" ] || [ "$SERVICE_STATE" = "activating" ]; then
  echo "FAIL: service is running; do not stop it automatically and do not run tests."
  exit 20
fi

if [ "$OBSERVED_HEAD" != "$EXPECTED_PROD_HEAD" ]; then
  echo "FAIL: observed production HEAD differs from the reported baseline; audit cannot claim acceptance."
  exit 21
fi
```

Reportuj:

| Item | Expected | Observed | Result |
|---|---|---|---|
| Runtime repo | discovered | ... | PASS/FAIL |
| Production HEAD | `791d16c` | ... | PASS/FAIL |
| Service | inactive/stopped | ... | PASS/FAIL |
| Working tree artifacts | report only | ... | INFO/BLOCKER |

## Task A2 — Candidate existence and scope, without fetch

```bash
cd "$RUNTIME_REPO"

if ! git cat-file -e "${EXPECTED_CANDIDATE}^{commit}" 2>/dev/null; then
  echo "FAIL: candidate is not present locally; no automatic fetch permitted."
  exit 22
fi

git show --stat --oneline "$EXPECTED_CANDIDATE"
git diff --name-status "$EXPECTED_PROD_HEAD..$EXPECTED_CANDIDATE"
git diff "$EXPECTED_PROD_HEAD..$EXPECTED_CANDIDATE" -- tests/ src/ scripts/
```

### Candidate scope: automatic FAIL

FAIL, pokud candidate mění cokoli mimo úzkou test/runtime-path izolaci, zejména:

```text
strategy / entry / exit / EV / PF / threshold behavior
learning eligibility or economic outcomes
TP/SL or sampler admission
Firebase/Android contract
live/REAL code
service/deploy/restart logic
runtime persistence semantics beyond test path injection
```

Povoleno: fixture, path injection nebo obdobná izolace, která pouze zabrání testům zapisovat do produkčních runtime souborů.

## Task A3 — Izolovaná candidate kopie

Testy nikdy nespouštěj v runtime checkoutu.

```bash
set -euo pipefail
AUDIT_ROOT="$(mktemp -d /tmp/cryptomaster_v41_audit_XXXXXX)"
AUDIT_REPO="$AUDIT_ROOT/repo"

git clone --no-hardlinks --no-local "$RUNTIME_REPO" "$AUDIT_REPO"
cd "$AUDIT_REPO"
git checkout --detach "$EXPECTED_CANDIDATE"

echo "AUDIT_ROOT=$AUDIT_ROOT"
echo "AUDIT_HEAD=$(git rev-parse HEAD)"
git status --short --untracked-files=all
mkdir -p "$AUDIT_ROOT/evidence"
```

## Task A4 — Najdi všechny runtime-state writery

```bash
cd "$AUDIT_REPO"

rg -n \
 'paper_open_positions|paper_adaptive_learning_state|server_local_backups|PAPER_POSITIONS|ADAPTIVE.*STATE|open_positions\.json|state\.json|journal|snapshot|close_paper_position|PAPER_CANONICAL_LEARNING_UPDATE|LEARNING_UPDATE|quarantin' \
 tests src scripts 2>/dev/null \
 | tee "$AUDIT_ROOT/evidence/state_writer_scan.txt" || true
```

V reportu klasifikuj každý relevantní match:

| File:line | Read/Write | Path | Redirected to tmp? | Evidence | PASS/FAIL |
|---|---|---|---|---|---|

Pokud nelze určit všechny aktivní write paths, STOP/FAIL: důkaz izolace není úplný.

## Task A5 — Manifest production i candidate runtime state

Známé cesty jsou pouze minimum. Rozšiř seznam o všechny aktivní paths nalezené v Task A4.

```bash
manifest_tree () {
  local root="$1"
  {
    for p in \
      "$root/data/paper_open_positions.json" \
      "$root/server_local_backups/paper_adaptive_learning_state.json"; do
      if [ -e "$p" ]; then
        sha256sum "$p"
      else
        echo "ABSENT  $p"
      fi
    done
    for d in "$root/data" "$root/server_local_backups"; do
      if [ -d "$d" ]; then
        find "$d" -type f -print0 | sort -z | xargs -0 -r sha256sum
      else
        echo "ABSENT_DIR  $d"
      fi
    done
  } | sort
}

manifest_tree "$RUNTIME_REPO" > "$AUDIT_ROOT/evidence/runtime_before.sha256"
manifest_tree "$AUDIT_REPO"   > "$AUDIT_ROOT/evidence/audit_before.sha256"
```

## Task A6 — Najdi skutečný established server-safe command

V4.0 vymýšlela nový pytest subset. To není důkaz parity s dříve přijatou suite.

```bash
cd "$AUDIT_REPO"
rg -n 'pytest|server-safe|requires_service|VERIFICATION|854 passed|935 passed|pytest.ini|pyproject' \
 README* CLAUDE* .github tests scripts pyproject.toml pytest.ini setup.cfg 2>/dev/null \
 | tee "$AUDIT_ROOT/evidence/test_command_search.txt" || true
```

Pravidla:

- Najdeš-li explicitní poslední schválený server-safe command, použij jej a cituj důkaz.
- Nenajdeš-li ho, smíš spustit konzervativní izolovanou diagnostickou suite, ale report musí říct `NOT COMPARABLE TO ACCEPTED BASELINE`.
- Relevantní legacy/hardcoded-path test nesmí být potichu ignorován.

## Task A7 — Targeted writer tests

Ze skenu sestav skutečný seznam testovacích souborů. Nepoužívej placeholder.

```bash
cd "$AUDIT_REPO"

TEST_TARGETS=(
  tests/<actual_state_writer_test_1>.py
  tests/<actual_state_writer_test_2>.py
)
printf 'Targeted test: %s\n' "${TEST_TARGETS[@]}"

# Použij již existující/ověřené projektové Python prostředí.
# Neinstaluj balíky do runtime checkoutu.
python -m pytest -q "${TEST_TARGETS[@]}" 2>&1 | tee "$AUDIT_ROOT/evidence/targeted_tests.txt"

manifest_tree "$RUNTIME_REPO" > "$AUDIT_ROOT/evidence/runtime_after_targeted.sha256"
manifest_tree "$AUDIT_REPO"   > "$AUDIT_ROOT/evidence/audit_after_targeted.sha256"

diff -u "$AUDIT_ROOT/evidence/runtime_before.sha256" "$AUDIT_ROOT/evidence/runtime_after_targeted.sha256" \
 || { echo "FAIL: production runtime state mutated during targeted tests"; exit 31; }

diff -u "$AUDIT_ROOT/evidence/audit_before.sha256" "$AUDIT_ROOT/evidence/audit_after_targeted.sha256" \
 || { echo "FAIL: tests still write runtime-style state inside candidate checkout"; exit 32; }
```

**Důvod dvojí kontroly:** Zápis do relativní `data/` cesty v audit checkoutu je rovněž FAIL; po deployi by zapsal do produkční cesty.

## Task A8 — Full isolated suite

Spusť pouze příkaz prokázaný v Task A6. Příklad níže nenahrazuje důkaz:

```bash
# EXAMPLE ONLY:
# python -m pytest -q 2>&1 | tee "$AUDIT_ROOT/evidence/full_suite.txt"
```

Po provedení:

```bash
manifest_tree "$RUNTIME_REPO" > "$AUDIT_ROOT/evidence/runtime_after_full.sha256"
manifest_tree "$AUDIT_REPO"   > "$AUDIT_ROOT/evidence/audit_after_full.sha256"

diff -u "$AUDIT_ROOT/evidence/runtime_before.sha256" "$AUDIT_ROOT/evidence/runtime_after_full.sha256" \
 || { echo "FAIL: production runtime state mutated during full tests"; exit 41; }

diff -u "$AUDIT_ROOT/evidence/audit_before.sha256" "$AUDIT_ROOT/evidence/audit_after_full.sha256" \
 || { echo "FAIL: full tests write candidate runtime-style state"; exit 42; }
```

### Phase 0A PASS podmínky

```text
- Observed production HEAD matches audited baseline.
- Candidate exists locally and its diff is only test/runtime isolation.
- State-writer targeted tests pass.
- Established server-safe suite passes with zero failures.
- Production runtime-state manifest unchanged.
- Candidate relative runtime-state manifest unchanged.
- No service action, code change, commit, fetch, deploy or restart occurred.
```

---

# PHASE 0B — BINANCE RUNTIME COMPATIBILITY INVENTORY
## ACTIVE NOW — read-only only

Isolation PASS nestačí k restartu, pokud runtime-used source používá Binance legacy WebSocket URL vyřazené 2026-04-23.

## Ověřené mapování pro audit

```text
/public:
  <symbol>@depth, <symbol>@depth@100ms/@500ms
  <symbol>@bookTicker
  <symbol>@rpiDepth@500ms

/market:
  <symbol>@markPrice, <symbol>@markPrice@1s
  <symbol>@aggTrade

/private:
  /ws/<listenKey> user-data stream
```

## Read-only inventory

```bash
cd "$AUDIT_REPO"
rg -n \
 'fstream\.binance\.com|@depth|@rpiDepth|@bookTicker|@markPrice|@aggTrade|listenKey|userDataStream|forceOrder|CONDITIONAL|ALGO_UPDATE|listen_key' \
 src bot2 start.py main.py tests scripts 2>/dev/null \
 | tee "$AUDIT_ROOT/evidence/binance_endpoint_inventory.txt" || true
```

V každém matchi rozliš:

- runtime-imported code,
- dead/legacy file,
- dokumentaci/test fixture.

| Runtime-imported component | Stream/API | Observed path | Required path | PASS/BLOCKER |
|---|---|---|---|---|

## Phase 0B pravidlo

Pokud runtime-imported code používá legacy WS route nebo chybné nové mapování, **neopravuj je v této session**. Výsledek musí být:

```text
PASS_ISOLATION_BUT_RESTART_BLOCKED
next task: separate WS compatibility patch prompt
service: KEEP STOPPED
```

---

# POVINNÝ VÝSTUP SOUČASNÉ SESSION

```markdown
# CryptoMaster V4.1 Phase 0 Acceptance Report

## Verdict
FAIL | PASS_ISOLATION_BUT_RESTART_BLOCKED | PASS

## Safety declaration
- No code changed:
- No commit/fetch/pull/deploy/merge in runtime checkout:
- No systemd action:
- Observed service state:

## Baseline verification
| Item | Expected reported baseline | Observed | Result |
|---|---|---|---|
| Runtime HEAD | 791d16c | ... | ... |
| Candidate locally available | b6311c2 | ... | ... |
| paper_open_positions | clean/empty | ... | ... |
| adaptive state | absent | ... | ... |

## Candidate scope audit
| File | Change type | Runtime behavior affected? | Allowed? | Evidence |
|---|---|---|---|---|

## State writer audit
| File:line | Runtime path | Test redirected to temp? | Evidence | Result |
|---|---|---|---|---|

## Runtime-state manifest proof
| Tree | Before | After targeted | After full | Identical? |
|---|---|---|---|---|
| Production runtime tree | ... | ... | ... | ... |
| Candidate audit tree | ... | ... | ... | ... |

## Tests
- Approved command evidence:
- Targeted command/result:
- Full suite command/result:
- Comparable to previously accepted baseline: YES | NO — reason

## Binance compatibility inventory
| Runtime component | Stream/API | Observed path | Required path | PASS/BLOCKER |
|---|---|---|---|---|

## Decision
- KEEP SERVICE STOPPED
- Next separate task permitted: NONE | WS_COMPATIBILITY_PATCH_PROMPT | PHASE_1_PROMPT_REVIEW
```

---

# LOCKED FUTURE SPECIFICATION — DO NOT IMPLEMENT NOW

Následující fáze jsou roadmapa. Claude je v aktuální session nesmí vykonat.

---

# PHASE 1 — CLEAN PAPER EPOCH + PROVENANCE

**Gate:** Phase 0 report PASS a samostatný lidský pokyn.

Přidej pouze:

```text
epoch_id
epoch_status = ACTIVE | SEALED | INVALIDATED
started_at_utc
runtime_commit
policy_version
config_hash
append-only provenance journal nebo minimální rozšíření jediného existujícího journalu
eligibility resolver
idempotent close evidence
```

Eligibility:

```text
missing epoch_id            -> False / INVALID_EPOCH
entry_ts < epoch.started_at -> False / PRE_EPOCH_TRADE
INVALIDATED epoch           -> False / INVALIDATED_EPOCH
quarantined/stale close     -> False / QUARANTINED_OR_STALE
test-generated record       -> False / TEST_GENERATED
duplicate close             -> no duplicate accounting/learning
valid current epoch close   -> True / VALID_CURRENT_EPOCH
```

**Zakázáno:** nová strategie, nový entry admission, cost/funding/fill změna, TP/SL/threshold tuning, Firebase redesign, REAL, automatický restart.

---

# PHASE 2 — MEASUREMENT-ONLY MARKET / EXECUTION TRUTH

**Gate:** čistý PAPER lifecycle stabilní a samostatný schválený prompt.

## Kritický princip

Nové execution/funding údaje nejprve ukládej jako verziovanou instrumentaci. Nesmí tiše přepsat stávající canonical learning PnL. Přechod na nový accounting model vyžaduje nový schválený epoch.

## Ověřené Binance rozhraní

```text
Diff depth:           /public, <symbol>@depth nebo @depth@100ms/@500ms
Book ticker:          /public, <symbol>@bookTicker; regular feed RPI vylučuje
RPI-inclusive depth:  /public, <symbol>@rpiDepth@500ms
RPI REST order book:  GET /fapi/v1/rpiDepth
Mark/funding:         /market, <symbol>@markPrice nebo <symbol>@markPrice@1s
Aggregate trades:     /market, <symbol>@aggTrade
User data:            /private/ws/<listenKey>
Commission:           GET /fapi/v1/commissionRate
Income history:       GET /fapi/v1/income; dostupná pouze poslední 3 měsíce
Leverage brackets:    GET /fapi/v1/leverageBracket
Symbol ADL risk:      GET /fapi/v1/symbolAdlRisk; low/medium/high, update ~30 min
```

## Measurement additions

```text
bid, ask, mid, spread_bps
mark_price and expected funding forecast
aggTrade q and nq captured as raw observables only
maker/taker/rpi commission schema loaded from API
expected_funding vs realized_funding reconciliation
fill observation fields, not canonical overwrite
exit type: TP / SL / SCRATCH / STAGNATION / TIMEOUT / FLAT
MFE/MAE/duration
tape checkpoint and book_sequence_valid
symbolAdlRisk and leverageBracket telemetry only
```

## Correct top-of-book fill observation

```python
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass(frozen=True)
class FillObservation:
    fill_price: Decimal
    mid_price: Decimal
    spread_bps: float
    explicit_impact_bps: float
    slippage_vs_mid_bps: float
    liquidity_visibility: str
    fill_model_version: str

def observe_top_of_book_taker_fill(
    side: Side,
    bid: Decimal,
    ask: Decimal,
    explicit_impact_bps: float = 0.0,
) -> FillObservation:
    if bid <= 0 or ask <= 0 or ask < bid:
        raise ValueError("invalid bid/ask")

    mid = (bid + ask) / Decimal("2")
    touch = ask if side == Side.BUY else bid
    impact = Decimal(str(explicit_impact_bps / 10_000))
    fill = touch * (Decimal("1") + impact) if side == Side.BUY \
        else touch * (Decimal("1") - impact)

    return FillObservation(
        fill_price=fill,
        mid_price=mid,
        spread_bps=float((ask - bid) / mid * Decimal("10000")),
        explicit_impact_bps=explicit_impact_bps,
        slippage_vs_mid_bps=float(abs(fill - mid) / mid * Decimal("10000")),
        liquidity_visibility="NON_RPI_PUBLIC_BOOK",
        fill_model_version="OBS_TOP_OF_BOOK_TAKER_V1",
    )
```

**Rule:** `mark_price` nikdy není fill price. RPI price improvement se v baseline nepředpokládá.

## Local order book integrity

```text
- Open depth stream on /public.
- Buffer events.
- Fetch REST depth snapshot.
- Drop events with u < lastUpdateId.
- First usable event satisfies U <= lastUpdateId and u >= lastUpdateId.
- Every subsequent event requires pu == previous_u.
- Any gap invalidates dependent measurements and forces snapshot rebuild.
```

## Funding

```text
expected_funding_bps:
  forecast from mark-price stream for measurement/future evaluation

realized_funding_bps:
  reconciled realized accounting event only
```

Zakázáno: `abs(funding_rate)` jako náklad; forecast použitý jako realized PnL.

## ADL

V4.0 navrhovala synthetic ADL close model bez ověřené kalibrace. V Phase 2:

```text
- pouze sbírej GET /fapi/v1/symbolAdlRisk jako telemetry
- nikdy nevytvářej syntetický ADL close
- nikdy nepoužívej ADL risk jako alpha/entry gate
```

## `nq` / VPIN

```text
- zachytávej q a nq jako raw measurement
- nepočítej VPIN do active policy
- VPIN vyžaduje budoucí offline methodology, leakage testy a vlastní confirmation
```

---

# PHASE 3 — ONE INTEGRATED PAPER HYPOTHESIS TAP

**Gate:** Phase 2 přijata a samostatně schválena.

Cíl: nová PAPER hypotéza může skutečně získat data bez starého historical PF/BAD veto, ale nesmí vzniknout druhý bot ani druhý truth store.

```text
validated feature snapshot
 -> raw DecisionFrame before historical-performance veto
 -> PAPER_HYPOTHESIS_TAP [feature flag default false]
      -> integrity/provenance/liquidity/pre-registered cost/risk gates
      -> shared PAPER executor
      -> shared durable journal
      -> evaluation_role=DISCOVERY
 -> legacy route continues unchanged
```

Metadata:

```text
decision_id, epoch_id, hypothesis_id, strategy_id, policy_version, config_hash
evaluation_role = DISCOVERY | CONFIRMATION | COMPARATOR | EXCLUDED_DIAGNOSTIC
eligible_for_learning, eligibility_reason
market_tape_checkpoint, accounting_model_version
```

První hypotéza `TREND_BREAKOUT_V1` je pouze testovatelná hypothesis, ne předem schválená strategie.

---

# PHASE 4 — DISCOVERY / CONFIRMATION EVALUATION

**Gate:** validní clean experimental outcomes a samostatný prompt.

## Povinné reportování

```text
mean realized net PnL bps
post-cost profit factor
gross PnL, fees, slippage, realized funding odděleně
exit attribution včetně STAGNATION/SCRATCH/TIMEOUT/FLAT
MFE/MAE a duration
worst trade, worst-k outcomes, expected shortfall/CVaR
max drawdown
PnL excluding best trade / excluding worst trade
concentration by symbol/regime/volatility
autocorrelation/time clustering
all excluded observations and reasons
```

## Žádné univerzální pass thresholds před měřením

V4.0 používala pevná pravidla (`n>=50`, `TIMEOUT+FLAT<40%`, `drawdown<15%`, `DSR>0.95`, `PBO<0.5`). V4.1 je chápe pouze jako možné reporting markers, ne automatické qualification gates.

Před confirmation musí být preregistrovány:

```text
policy/config freeze
universe
accounting model
minimum meaningful net edge
sample/precision stop rule
tail-risk gates
exclusion rules
```

## Bootstrap

Stationary/block bootstrap je vhodný pro závislé outcomes; implementace musí být samostatně otestována a její block-length method uložena v registry.

## DSR correction

Neimplementuj pseudo-kód z V4.0. DSR má smysl pouze v auditovaném offline evaluatoru s:
- správnými comparable strategy trials,
- publikovanou formulí,
- golden numerical tests,
- jasnou definicí non-annualized return series a trial variance.

## CSCV/PBO correction

CSCV/PBO používej pouze tehdy, když jsou varianty vyhodnoceny na stejném offline point-in-time replay datasetu. Není to samostatný PASS test jednoho forward PAPER streamu.

## Promotion outcome

```text
Discovery promising -> freeze policy for confirmation only.
Confirmation pass -> human-reviewed readiness report only.
REAL remains disabled.
```

---

# FUTURE RESEARCH ONLY

| Výzkum | Podmínka |
|---|---|
| Passive/maker/RPI-aware execution | Až po konzervativním taker measurement baseline a adverse-selection analýze |
| VPIN/order-flow toxicity | Offline study first; žádný okamžitý sizing/entry gate |
| Hedged carry | Samostatný design; nemíchat s directional strategií |
| Cross-sectional momentum | Point-in-time universe + survivorship controls |
| ML meta-filter | Pouze na clean post-cost datech |
| RL core | Neschváleno jako první architektura |

---

# SOURCES TO KEEP IN RESEARCH RECORD

## Official Binance documentation

- USDⓈ-M Futures WebSocket System Upgrade Notice, 2026-03-06.
- WebSocket streams: Diff Book Depth, RPI Diff Book Depth, Individual Symbol Book Ticker, Aggregate Trade, Mark Price.
- How To Manage A Local Order Book Correctly.
- User Data Streams Connect.
- User Commission Rate.
- RPI Order Book.
- Get Income History.
- Notional and Leverage Brackets.
- Query ADL risk rating.
- Derivatives Change Log.

## Research/statistics references

- Liu & Tsyvinski (2021), *Risks and Returns of Cryptocurrency*, Review of Financial Studies.
- Liu, Tsyvinski & Wu (2022), *Common Risk Factors in Cryptocurrency*, Journal of Finance.
- Grobys et al. (2025), *Cryptocurrency momentum has (not) its moments*, Financial Markets and Portfolio Management.
- Schmeling, Schrimpf & Todorov (2026), *Crypto Carry*, Management Science.
- Easley, O’Hara, Yang & Zhang (2024), *Microstructure and Market Dynamics in Crypto Markets*, SSRN working paper.
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*.
- Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*.
- Politis & White (2004); Patton, Politis & White (2009 correction), block bootstrap length selection.

---

# FINAL COMMAND FOR CLAUDE CODE NOW

```text
Execute only PHASE 0A and PHASE 0B from this document.
Do not modify code.
Do not fetch candidate automatically.
Do not implement any future phase.
Do not start, stop or restart cryptomaster.service.
Do not deploy or commit.
Return the required CryptoMaster V4.1 Phase 0 Acceptance Report.
```
