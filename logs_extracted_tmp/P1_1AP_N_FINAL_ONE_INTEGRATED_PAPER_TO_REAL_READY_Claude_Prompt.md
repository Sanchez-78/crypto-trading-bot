# CLAUDE CODE — P1.1AP-N FINAL: JEDEN INTEGROVANÝ PAPER → LEARNING → REAL WORKFLOW

## Toto zadání nahrazuje všechny předchozí P1.1AP-N / Phase 2 / Firebase probe prompty

Uživatel nechce další audity, shadow bucket, oddělenou epochu, paralelní learner ani Git feature branch.

CryptoMaster je dnes **paper/tréninkový bot**. Má fungovat jako jeden integrovaný systém:

```text
PAPER obchodování
→ každý způsobilý uzavřený paper obchod aktualizuje canonical learning metriky
→ aktualizované metriky mění následující paper rozhodnutí
→ při prokázané dlouhodobé kvalitě po nákladech vznikne REAL_READY
→ real obchodování může být aktivováno pouze přes jasný kontrolovaný real-mode unlock a risk gates
```

Cílem této implementace je, aby se bot skutečně učil, upravoval metriky a zlepšoval své paper rozhodování. Nejde o další report ani sběr shadow dat.

---

# 1. Současný stav

Repo může být na:

```text
20944de P1.1AP-M: Phase 2B Firebase schema probe — preparation complete
735ba35 Revert P1.1AP-L shadow sampler experiment
321f10b Tests: Replace legacy boolean-return pytest checks with assertions
eb259e3 P1.1AP-J2: Emit B_RECOVERY_READY exit attribution diagnostics
008559e P1.1AP-K: Normalize ATR price move before C_WEAK cost-edge gate
07fc451 P1.1AP-I2: Suppress D_NEG legacy LEARNING_UPDATE log
e80807d P1.1AP-I: Isolate D_NEG_EV_CONTROL from canonical learning
```

Důležité:

```text
- 20944de přidalo jen research/probe soubory, nikoli runtime trading logiku.
- P1.1AP-L/L1 E-shadow experiment je revertovaný a NESMÍ se obnovit.
- Historický canonical výsledek je špatný: PF≈0.49, net PnL<0, health=BAD.
- Bot běží v paper/training režimu a má 0 paper otevřených pozic v poslední ověřené kontrole.
- Aktuální problém: staré BAD metriky prakticky zablokují nové učící paper obchody, takže se metriky nemají jak zlepšit.
```

Zachovej:

```text
P1.1AP-I/I2: D_NEG_EV_CONTROL je mimo learning a nesmí emitovat canonical LEARNING_UPDATE.
P1.1AP-J/J2: B_RECOVERY_READY telemetry/attribution zůstává.
P1.1AP-K: ATR normalizace a cost-edge telemetry zůstává.
```

---

# 2. Pracovní pravidlo: žádná větev, jeden implementační průchod

Nezakládej Git branch. Pracuj v aktuálním checkoutu.

Protože push do `main` automaticky restartuje běžícího bota:

```text
1. Proveď inspekci.
2. Implementuj pouze nutné runtime/test změny.
3. Spusť všechny požadované testy.
4. Ověř scope diffu.
5. Pokud testy projdou a scope je čistý, vytvoř JEDEN commit a pushni jej do main.
6. Po auto-deploy zkontroluj logy.
```

Commit/push proveď pouze pokud:

```text
- 0 test failures,
- 0 warnings v server-safe suite,
- nebyly změněny zakázané soubory,
- diff neobsahuje runtime data, research, probe, .env nebo logy.
```

---

# 3. Inspekce před implementací

Spusť:

```bash
cd /opt/CryptoMaster_srv

git rev-parse --short HEAD
git status --short
git log --oneline -12

git diff --name-status 735ba35..HEAD -- src tests VERIFICATION_V10_13W

grep -R "paper_train\|paper_mode\|PAPER_TRAIN\|PAPER_EXIT\|C_WEAK_EV_TRAIN\|B_RECOVERY_READY\|D_NEG_EV_CONTROL\|PAPER_LEARNING_SHADOW_SKIP" -n src/services tests | head -700

grep -R "REJECT_ECON_BAD_ENTRY\|ECON_BAD\|lm_economic_health\|canonical_closed_trades\|cost_edge_too_low\|training_sampler" -n src/services tests | head -700

grep -R "update_from_paper_trade\|LEARNING_UPDATE\|LM_STATE_AFTER_UPDATE\|feature_weights\|calibrat\|policy\|max_seen\|min_seen\|mfe_pct\|mae_pct" -n src/services tests | head -700

grep -R "paper\|live\|real\|execution_mode\|trade_environment\|ENABLE_REAL" -n src/services start.py main.py tests | head -500
```

Před editací stručně zaznamenej:

```text
A. Funkce, která přijímá/routuje paper kandidáty.
B. Přesný gate, který dnes kvůli starému BAD/PF způsobuje learning starvation.
C. Funkce, která zavírá paper obchod a aktualizuje learning.
D. Existující metriky/weights/policy, které už rozhodování ovlivňují a mají se znovu použít.
E. Současný guard pro paper/real režim.
F. Minimální soubory, které změníš.
```

---

# 4. Zásadní architektura: jeden canonical learner

Nevytvářej:

```text
- nový shadow bucket,
- E_ECON_BAD_NEAR_MISS_SHADOW,
- oddělený learner,
- oddělenou "epoch truth",
- paralelní PF/health databázi, která neovlivňuje rozhodování.
```

Použij existující canonical paper learning stream.

V rámci stejného learneru udržuj:

```text
A. lifetime metrics:
   celá historie, včetně starého špatného PF; nikdy ji nemaž.

B. rolling metrics:
   posledních 20 / 50 / 100 / případně 200 způsobilých paper closes;
   tyto metriky řídí aktuální adaptaci a REAL_READY kvalifikaci.
```

To nejsou větve. Jsou to auditní a současné pohledy nad jedním learning streamem.

Z learningu dále vyřazuj:

```text
- D_NEG_EV_CONTROL,
- quarantined/corrupt/stale positions,
- invalid/no-price closes, pokud je současný systém již neumí bezpečně učit.
```

---

# 5. Obnov paper trade flow

## 5.1 Problém k opravě

Historický `health=BAD` / `PF≈0.49` nesmí v paper režimu trvale zabránit vytvoření nových způsobilých learning vzorků.

V paper režimu musí bot dál testovat validní pozitivní kandidáty, měřit jejich post-cost výsledek a podle výsledku adaptovat politiku.

## 5.2 Routovací pravidla

Priorita:

```text
1. Kandidát, který projde existující normální paper learning cestou, zůstává na ní.
2. Validní pozitivní paper kandidát blokovaný pouze historickým ECON_BAD / training-starvation gate může být přijat do stejného canonical paper learning streamu s metadata:
   learning_source=paper_adaptive_recovery
3. D_NEG_EV_CONTROL zůstává oddělený a do canonical learneru nikdy nevstupuje.
4. Kandidáti bez side, bez validní ceny nebo NO_CANDIDATE_PATTERN se nepřijímají.
```

Minimální způsobilost adaptive recovery paper vzorku:

```text
- mode je paper_train/paper;
- symbol existuje;
- side je BUY nebo SELL;
- cena a nezbytná metadata jsou validní;
- EV > 0;
- original_decision a reject_reason jsou zaznamenány;
- regime/score/EV jsou uchovány, pokud existují;
- expected_move_pct, expected_move_src, cost_edge_ok a cost metadata jsou uchovány.
```

V PAPER learning režimu může být kontrolovaně přijat i pozitivní kandidát, který neprošel cost-edge, protože právě post-cost výsledek má learneru ukázat, že takový segment je fee-dominated a má být později omezen.

Toto není povolení pro reálné objednávky.

## 5.3 Limity paper tréninku

Použij konfigurovatelné limity:

```text
PAPER_LEARN_MAX_OPEN_GLOBAL = 3
PAPER_LEARN_MAX_OPEN_PER_SYMBOL = 1
PAPER_LEARN_MAX_ENTRIES_PER_HOUR = 12
PAPER_LEARN_MAX_ENTRIES_PER_DAY = 100
PAPER_LEARN_BOOTSTRAP_MIN_CLOSES = 20
```

Pro první implementaci zachovej současnou TP/SL/timeout geometrickou logiku a současný cost model. Neměň současně sampling i exity.

Logy vstupu:

```text
[PAPER_LEARNING_ENTRY]
trade_id=...
learning_source=paper_adaptive_recovery
symbol=... side=... regime=... ev=... score=...
original_decision=... reject_reason=...
expected_move_pct=... expected_move_src=... cost_edge_ok=...
historical_health=BAD admission_reason=paper_learning_must_continue
```

Logy blokace:

```text
[PAPER_LEARNING_ENTRY_BLOCKED]
reason=max_open_global|max_open_symbol|max_entries_hour|max_entries_day|invalid_candidate|negative_ev
symbol=... side=... ev=...
```

---

# 6. Každý close musí aktualizovat metriky

Pro každý způsobilý canonical paper close ulož/propaguj dle dostupnosti:

```text
trade_id
symbol
side
entry_regime
exit_regime
entry_ts / exit_ts
entry / exit
learning_source
original_decision / original_reject_reason
ev / score
expected_move_pct / expected_move_src / cost_edge_ok
gross_move_pct
fee_drag_pct nebo fee/slippage
net_pnl_pct
reason / outcome
hold_s
tp_pct / sl_pct
mfe_pct / mae_pct nebo max_seen/min_seen
```

Po každém close aktualizuj:

```text
- lifetime canonical metrics,
- rolling20 metrics,
- rolling50 metrics,
- rolling100 metrics,
- segment metrics podle stávajícího stabilního klíče, preferovaně symbol × regime × side,
- exit-reason metrics.
```

Povinný log:

```text
[PAPER_CANONICAL_LEARNING_UPDATE]
trade_id=... symbol=... side=... regime=... learning_source=...
reason=... outcome=... net_pnl_pct=... mfe_pct=... mae_pct=...
lifetime_n=... lifetime_pf=...
rolling20_n=... rolling20_pf=... rolling20_expectancy=...
rolling50_n=... rolling50_pf=... rolling50_expectancy=...
rolling100_n=... rolling100_pf=... rolling100_expectancy=...
segment=... segment_n=... segment_pf=... segment_expectancy=...
policy_action=...
```

Pokud způsobilý close neaktualizuje metrics:

```text
[PAPER_LEARNING_ANOMALY]
reason=eligible_close_without_metric_update trade_id=... symbol=...
```

---

# 7. Metriky musí měnit další paper rozhodování

Learning bez změny rozhodování není learning.

Použij existující feature weights/calibrator/policy mechanismus, pokud je vhodný. Pokud chybí, přidej co nejmenší bounded rolling-policy vrstvu přímo do stávající canonical paper cesty.

## 7.1 Bootstrap

```text
rolling eligible closes < 20:
- pokračuj ve sběru validních paper vzorků pod capy;
- neblokuj segment pouze z malé statistiky;
- policy_action=collect_bootstrap.
```

## 7.2 Adaptace po dostatku dat

Použij existující segmentaci, preferovaně:

```text
symbol × regime × side
```

Minimální pravidla:

```text
pokud segment_n >= 20 a segment_pf < 0.80 a segment_expectancy < 0:
    sniž jeho váhu/prioritu pro další paper admissions;
    action=downweight_losing_segment

pokud segment_n >= 20 a segment_pf > 1.10 a segment_expectancy > 0:
    zvyš/preferuj jeho váhu v rámci capů;
    action=prefer_improving_segment

jinak:
    action=continue_learning
```

Váhy musí být omezené a reverzibilní:

```text
min_weight = 0.25
max_weight = 2.00
žádný tvrdý zákaz segmentu před n >= 30, pokud jej nevyžaduje existující validní bezpečnostní pravidlo
```

Povinný log:

```text
[PAPER_POLICY_ADAPTATION]
segment=... n=... pf=... expectancy=...
old_weight=... new_weight=...
action=... reason=post_cost_rolling_learning
```

Test musí prokázat, že po aktualizaci metrics se další paper rozhodnutí/priorita skutečně změní.

---

# 8. Přechod na real trade: kvalifikace, ne slepý přepínač

Bot se má umět dopracovat k real trade, ale ne na základě jedné série výher nebo zavádějící WR.

Implementuj lifecycle:

```text
PAPER_COLLECTING
PAPER_ADAPTING
PAPER_VALIDATING
REAL_READY
REAL_ACTIVE
REAL_SUSPENDED
```

Aktuální provoz po nasazení této změny zůstává PAPER.

## 8.1 REAL_READY podmínky

Bot smí vyhlásit `REAL_READY` pouze pokud všechny podmínky platí nad novými rolling paper výsledky po implementaci:

```text
- nejméně 100 nových způsobilých paper closes;
- rolling100 PF >= 1.20 po fees/slippage;
- rolling100 expectancy > 0 po fees/slippage;
- rolling100 net PnL > 0;
- rolling20 PF > 1.00 a rolling20 expectancy > 0;
- drawdown je pod existujícím konzervativním risk limitem;
- výsledky nejsou koncentrované v jediném segmentu:
    alespoň 3 obchodované symboly,
    žádný jediný segment netvoří >60 % čistého zisku;
- žádné nevyřešené PAPER_LEARNING_ANOMALY;
- bot zůstává paper, dokud není aktivován real-mode unlock.
```

Log:

```text
[REAL_READINESS_CHECK]
eligible=False
paper_closed=...
rolling100_pf=...
rolling100_expectancy=...
rolling100_net_pnl=...
rolling20_pf=...
drawdown=...
symbols=...
max_segment_profit_share=...
reason=...

[REAL_READY]
eligible=True current_mode=PAPER operator_unlock_required=True
```

## 8.2 Aktivace REAL_ACTIVE

Zjisti existující mechanismus pro real/live režim. Pokud již existuje, zapoj readiness jako nutnou podmínku.

Real obchodování nesmí začít jen proto, že `REAL_READY=True`. Vyžaduje:

```text
REAL_READY=True
AND explicit operator real-mode unlock/config already used by project
AND stávající risk/circuit-breaker kontroly projdou
```

To není blokování cíle; je to řízený finální přechod z ověřeného paper learningu do skutečného provedení.

V této implementaci/deploy fázi real mode NEZAPÍNEJ. Implementuj jeho gating a stav.

---

# 9. Persistence a restart

Použij existující persistence learning stavu, pokud existuje.

Rolling metrics a policy váhy musí přežít restart:

```text
- atomický zápis;
- bezpečné načtení;
- corrupt state = backup/quarantine + bezpečný fallback;
- žádný reset lifetime metrik;
- D_NEG není importovaný do rolling learneru.
```

Pokud je nezbytný nový runtime soubor, musí být ignorován v Gitu.

Log po startu:

```text
[PAPER_LEARNING_STATE_RESTORE]
state_ok=True lifetime_n=... rolling_n=... segments=... lifecycle=PAPER_ADAPTING
```

---

# 10. Zakázané změny

Neměň v tomto úkolu:

```text
data/research/*
phase2b_firebase_probe.py
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android/Firebase dashboard contracts
E_ECON_BAD_NEAR_MISS_SHADOW
D_NEG isolation semantics
P1.1AP-K ATR normalization semantics
P1.1AP-J2 B attribution behavior
runtime JSON/log artifacts do commitu
.env*, venv/, server_local_backups/
```

---

# 11. Povinné testy

## Paper flow

1. Lifetime `health=BAD` už nezablokuje validní pozitivní paper learning kandidát.
2. Staré lifetime metriky zůstanou zachované.
3. Invalid/no-side/no-price kandidáti zůstanou odmítnutí.
4. Negative EV / D_NEG nevstoupí do canonical ani rolling learneru.
5. Normální existující paper route má prioritu před adaptive recovery.
6. Cost-edge-rejected pozitivní kandidát může v PAPER learningu projít jen kontrolovaně a zachová cost metadata.

## Capy

7. Global open cap = 3.
8. Per-symbol cap = 1.
9. Hour cap = 12.
10. Daily cap = 100.

## Metrics

11. Každý způsobilý close aktualizuje lifetime i rolling metrics právě jednou.
12. D_NEG/quarantine/invalid close metrics neaktualizuje.
13. Scratch/stagnation ztráty snižují rolling PF/expectancy.
14. Profitable close rolling metrics zvyšuje.
15. MFE/MAE/cost pole jsou propagována, pokud jsou dostupná.

## Adaptace

16. Před 20 close zůstává bootstrap sběr.
17. Dostatečně vzorkovaný ztrátový segment dostane bounded downweight.
18. Dostatečně vzorkovaný zlepšující segment dostane bounded preference.
19. Aktualizovaná policy změní další paper rozhodnutí nebo prioritu.
20. Žádné předčasné označení za ready.

## Real readiness

21. `REAL_READY` selže před 100 novými closes.
22. Selže při PF < 1.20.
23. Selže při záporné expectancy nebo net PnL.
24. Selže při koncentraci zisku.
25. Projde pouze pokud projdou všechny gates.
26. `REAL_READY` samo nespustí skutečné objednávky bez explicitního real unlocku.

## Regrese

27. I/I2 D_NEG testy projdou.
28. J/J2 B telemetry testy projdou.
29. K cost-edge/ATR normalizační testy projdou.
30. Full server-safe suite projde bez failures a warnings.

Spusť:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_v10_13u_patches.py \
  <nový test soubor pro integrated adaptive paper learning>

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

---

# 12. Jeden commit a deploy

Po implementaci a úspěšných testech:

```bash
git status --short
git diff --name-status
git diff --stat
```

Ověř, že diff obsahuje jen nutné runtime/test soubory a případně `.gitignore`.

Pokud scope i testy projdou, vytvoř jediný commit a push do main:

```bash
git add <jen povolené src/test/.gitignore soubory>
git commit -m "P1.1AP-N: Integrate adaptive paper learning and real-readiness gate"
git push origin main
```

Auto-deploy/restart je pro tento jediný otestovaný runtime commit očekávaný.

Po deploy sleduj:

```bash
sudo journalctl -u cryptomaster -f -o cat | grep --line-buffered -E \
"PAPER_LEARNING_ENTRY|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_POLICY_ADAPTATION|LEARNING_LIFECYCLE_STATE|REAL_READINESS_CHECK|REAL_READY|D_NEG_EV_CONTROL|PAPER_EXIT|Traceback|UnboundLocalError"
```

Akceptace po deploy:

```text
- bot otevírá nové paper learning obchody;
- každý způsobilý close aktualizuje metriky;
- rolling PF/expectancy se mění;
- po dostatku vzorků policy ovlivňuje další paper rozhodování;
- D_NEG neovlivňuje learner;
- REAL_READY zůstává false, dokud nejsou splněné výsledkové gates;
- žádný crash.
```

---

# Report zpět

Vrať:

```text
ROOT CAUSE OPRAVEN:
JAK BYL OBNOVEN PAPER FLOW:
JAK CLOSE AKTUALIZUJE METRIKY:
JAK METRIKY MĚNÍ DALŠÍ PAPER ROZHODNUTÍ:
JAK JE ŘÍZEN PŘECHOD DO REAL MODE:
ZMĚNĚNÉ SOUBORY:
TEST RESULTS:
COMMIT HASH / PUSH:
POST-DEPLOY LOG EVIDENCE:
```
