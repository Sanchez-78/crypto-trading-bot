# Externí audit — CryptoMaster HF-Quant 5.0 (kolo 4: re-verifikace + ROZHODNUTÍ o zbývajících položkách)

**Od:** provozovatel bota
**Předmět:** Potvrdit uzavření Round-3 nálezů + vydat **GO / NO-GO rozhodnutí** o všech zbývajících (operátorem/daty gated) položkách
**Datum:** 17. 7. 2026
**Auditovat @ commit:** `5a26731` (větev `main`)

---

## 0. Absolutní mantinel (beze změny)

**REAL trading = NO-GO.** Vše paper (`TRADING_MODE=paper_train`, live objednávky čtyřnásobně gaté). Nesnižuj náklady, neměň edge jako vedlejší efekt, netiskni secrets, ke každému tvrzení `file:line` / artefakt. „Runtime ověřeno" jen po analýze čerstvého serverového artefaktu.

---

## 1. Co se od kola 3 změnilo (k re-verifikaci)

Round-3 report downgradoval F2/F3 a F5 na PARTIAL a dal spec. **Všechny Round-3 residua a otevřené kódové položky jsou hotové** (každá reviewer-gated; F1 trading-safety; F6/F7 android-contract).

| Nález | Round-3 verdikt | Round-4 stav | PR |
|-------|-----------------|--------------|----|
| **F2/F3** deploy fail-open | PARTIAL/REJECT | READY marker (post-init) řídí restart; missing READY = fail-closed restart; zero-position gate fail-closed (python parse, UNKNOWN→refuse); root-owned `.deploy_hold` + TTL; `deployed_bot_sha` až po `is-active`+READY konvergenci | #72 |
| **F5** unknown mode no-op | PARTIAL | jen unset/off/shadow startuje; authoritative + jakákoli neznámá/překlep hodnota = fail-closed | #72 |
| **F6/F7** headline + dual PF | OPEN | jeden `headline` objekt (wins/losses/flats/WR/net stejné okno); browser čte `data.headline.*`, FLAT vlastní výseč; dual PF (`_pct_basis`/`_usd_basis`); Android kontrakt zachován | #74 |
| **F8** MFE/MAE | OPEN/HIGH VALUE | `trade_excursion.py`: gross MFE/MAE (fraction+pct+bps, side-aware) + `time_to_mfe/mae` (pořadí extrémů) + `favorable_first()`; additivní cache sloupce. **F8b (1s price-path) odloženo.** | #73 |
| **F9** log | REOPENED | Round-3 sekce v `AUDIT_CHANGES_LOG.md`; zastaralé tabulky odstraněny | #72 |
| **F10** firewall | OPEN | fail-closed verify (ufw active, IPv4 deny, IPv6 warn, local health) + externí runner probe (selže když public 5001 dosažitelný) + `ROLLBACK_FIREWALL` mód | #75 |
| **F11** single-step `lifetime_n` | PENDING (runtime) | **runtime-potvrzeno** ze snapshotu (viz §4) | — |
| **F1** runtime sign-off | PENDING (artefakt) | **runtime-potvrzeno** (viz §4) | #69 |
| **Nový** :5000 dashboard crash | (odhaleno runtime) | `simple_dashboard.py:575` iteroval nedefinovaný `closed_trades` → crash na každý public scan; opraveno guardem + try/except | #76 |

**Řetězec:** #62–#67 (master P0–P2), #68 (ship-dark incident), #69 (F1), #70 (F4/F5/F9), #71+#72 (F2/F3+F5 r2), #73 (F8), #74 (F6/F7), #75 (F10), #76 (:5000 fix).

---

## 2. Připojení na server (read-only)

**`hetzner-fetch-health.yml`** (`workflow_dispatch`) → artefakt `cryptomaster-health-<N>`. **Nově** obsahuje:
- `deploy_diagnostics.txt` → trojice/čtveřice SHA identit: `repo_head_sha` / `deployed_bot_sha` / `ready_bot_sha` / `boot_bot_sha` + `.deploy_hold` uid.
- `recent_exceptions.txt` → celé tělo traceback + kontext (sanitizované).
- `canonical_pipeline_probe.txt` → PR6 shadow stav.
Secrets se netisknou. **Pozn.:** server může být za `main` (autodeploy 2h stahuje postupně) — porovnej SHA identity.

---

## 3. Re-verifikační úkoly (uzavřel každý nález, nebo obchází?)

1. **F2/F3 (#72):** ověř bash restart-decision pod `set -euo pipefail`: missing READY→fail-closed restart (ne skip); code-impact gate (docs-only nerestartuje); zero-position python parse (UNKNOWN→refuse); root-owned hold + TTL; `deployed_bot_sha` až po `is-active`+READY. Najdeš cestu, jak nechat stale proces bez restartu nebo jak skript aboruje? Je READY marker (`bot2/main.py` na „BOOTSTRAP COMPLETE") skutečně po celém initu?
2. **F5 (#72):** off/shadow/unset startují; authoritative + neznámá hodnota fail-closed. Live server (`PAPER_CANONICAL_PIPELINE` unset) startuje?
3. **F6/F7 (#74):** `headline.win_rate_pct == top-level win_rate_pct`; browser nenásobí lifetime×WR; FLAT vlastní výseč; dual PF se liší při proměnlivé size; Android top-level klíče netknuté.
4. **F8 (#73):** `compute_excursion` side-aware znaménka + jednotky; `max_seen/min_seen` HODNOTY identické se starým `max()/min()` (jen přibyly ts); `time_to_mfe/mae` zachytí pořadí; **žádná změna close matematiky** (golden). Je F8a (globální extrémy + ts) dostatečná, nebo trváš na F8b (per-level 1s path) před edge rozhodnutím? (viz §5.3)
5. **F10 (#75):** fail-closed verify polarita; externí probe (connect→fail); rollback; dispatch-only (neběží).
6. **:5000 fix (#76):** guard skutečně zabraňuje crashi na všech malformed vstupech; nedegraduje trading proces.

---

## 4. Runtime důkazy k validaci (snapshot `health-530/531`, server `fdcb5e9`)

- **F1 sign-off:** žádná zmínka `EXECUTION_ENGINE` v celém snapshotu (engine neaktivní, `!= 1`); `paper_train`, `live_real allowed: false`, ENABLE_REAL_ORDERS/LIVE_TRADING_CONFIRMED false. → *„žádná runtime cesta nedosáhne reálného order submission"* — **potvrď nebo vyvrať** proti čerstvému artefaktu.
- **F11 single-step:** `close_path_forensics` ukazuje `lifetime_n` 16980→16981→16982→16983→16984→16985, **+1 na eligible close**, žádný duplicitní `[PAPER_CANONICAL_LEARNING_UPDATE]` pro stejný `trade_id`. TIMEOUT_NO_PRICE nebyl (běžný TIMEOUT s cenou je eligible). **Ověř nezávisle.**
- **F2/F3 mechanismus:** `boot_bot_sha=fdcb5e9` (BOOT marker se píše ✓); `ready_bot_sha=none`/`deployed_bot_sha=none` — protože server je na `fdcb5e9` (PŘED #72, kde READY přibyl); self-heal po autodeploy pulu. **Ověř z čerstvého artefaktu, že po dotažení #72–#76 jsou repo/deployed/ready konzistentní.**
- **:5000 traceback:** identifikován jako `simple_dashboard.py:575` (public scan `3.131.220.121`), non-fatal, opraveno #76.
- **Edge (nezměněná, mírně horší):** lifetime PF 0,28–0,34, 24h PF 0,295, vše TIMEOUT; BULL ztráty `mfe_pct=0.0` (cena nikdy favorable), BEAR closy `mfe~0.4` ale FLAT (nedosáhly TP ~54 bps). **Přepočítej segmentově z `cache.sqlite`; dashboard neber jako zdroj pravdy.**

---

## 5. ROZHODNUTÍ AUDITORA — GO / NO-GO o zbývajících položkách

Ke každé vydej **GO / GO-S-PODMÍNKOU / NO-GO**, kritéria úspěchu, a zda smí autonomní agent nebo to vyžaduje operátora.

### 5.1 Zapnout `DASHBOARD_SECURITY_ENABLED=1`?
Aktuálně ship-dark (default off = veřejné bez auth, aby Android fungoval). Preflight checklist je v `EXTERNAL_AUDIT_PROMPT_v3.md` §11 krok 6. **Rozhodni:** jsou podmínky správné a úplné? Je canary postup dostatečný? Přesně které kroky musí proběhnout a v jakém pořadí, a co je fail-closed rollback, který neotevře veřejný port? Zahrnuje to i port **5000** (druhý dashboard)?

### 5.2 Zapnout `PAPER_CANONICAL_PIPELINE=shadow`, a poté Phase B?
Shadow je log-only (bezpečné). **Rozhodni:** GO na shadow teď? Shadow success kritéria (Round-3 §11 krok 7: ≥50 eligible closes, 100% eligibility+effect-plan agreement, 0 side-effect writes, 0 duplicate learning). Phase B: jaké přesně invarianty (effect worker, idempotency, position-removal, conflict quarantine, failure injection, full parity) musí být hotové a nezávisle ověřené před authoritative cutoverem?

### 5.3 Edge — offline counterfactual (E1–E4)?
F8a persistuje gross MFE/MAE + `time_to_mfe/mae` (pořadí globálních extrémů). **Rozhodni klíčovou věc:** je F8a dostatečná evidence pro první offline counterfactual (favorable_first proxy), nebo je **F8b (per-level 1s directional path)** nezbytný předpoklad, protože sweeping více kandidátních TP/SL úrovní potřebuje intra-trade crossing sekvenci? Potvrď E2–E4 kritéria (≥200 closes, ≥30/segment, walk-forward, out-of-sample PF≥1,20, expectancy>0 po 18bps, žádný symbol >40 % zisku). Připomínám: **žádná změna TP/SL/timeout/nákladů/entry/sizing bez tohoto.**

### 5.4 F8b (1s price-path tabulka) — priorita?
**GO / odložit?** Dotýká se per-tick hot path. Pokud GO, potvrď kvóta-safe model (in-memory agregace do 1s directional OHLC, persist jednou při close, žádný per-tick Firestore) a schéma.

### 5.5 Autodeploy model
Nechat s current gaty (#72: READY-based restart + code-impact + hold + zero-position), nebo přejít na plný **operator-approval** (timer jen fetch+audit+notify, deploy jen ruční)? Round-3 §4.8 doporučoval operator-approval. **Rozhodni** a dej kritéria.

### 5.6 Druhý dashboard na portu 5000 (`simple_dashboard.py`)
Je redundantní s Flask :5001 read-modelem, je veřejný a skenovaný. **Rozhodni:** vypnout / bind localhost / ponechat? Vztah k security enable (5.1).

---

## 6. Očekávaný výstup

1. **Re-verifikační tabulka:** per nález **CLOSED / PARTIAL / REOPENED** + důkaz.
2. **Rozhodnutí §5.1–5.6:** GO/NO-GO + kritéria + kdo (autonomní/operátor) + pořadí.
3. **Doporučené pořadí dalších kroků** (hodnota/riziko).
4. **Explicitní bezpečnostní potvrzení** pro `5a26731`: lze teď (s runtime artefaktem) podepsat *„žádná runtime cesta nedosáhne reálného order submission"*, nebo co ještě chybí?

---

Díky. Runtime read-only přes `hetzner-fetch-health.yml`; hands-on read-only SSH na vyžádání bezpečným kanálem.
