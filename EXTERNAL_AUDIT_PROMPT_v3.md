# Externí audit — CryptoMaster HF-Quant 5.0 (kolo 3: re-verifikace remediace + návrh pokračování)

**Od:** provozovatel bota
**Předmět:** Nezávislé ověření, že Round-2 nálezy byly skutečně uzavřeny + **návrh pokračování od auditora**
**Datum:** 17. 7. 2026
**Auditovat @ commit:** `6f44bd1` (větev `main`)

---

## 0. Absolutní mantinel (beze změny)

**REAL trading = NO-GO.** Vše je paper (`TRADING_MODE=paper_train`, live objednávky čtyřnásobně gaté). Nesnižuj simulované náklady, neměň edge/strategii jako vedlejší efekt, netiskni secrets, ke každému tvrzení `file:line` nebo artefakt. „Runtime ověřeno" jen po analýze čerstvého serverového artefaktu.

---

## 1. Co se od kola 2 změnilo — remediace ke re-verifikaci

Tvůj Round-2 report (`CryptoMaster_EXTERNAL_AUDIT_REPORT_v2`) vydal REJECT s 11 nálezy. **Všechny Critical a High byly opraveny** (každá změna prošla adversariálním reviewer-gatem; F1 navíc trading-safety). Ověř, že opravy skutečně uzavírají nálezy — a hledej regrese a obcházení.

| Nález | Severity | Oprava (PR) | Klíčové `file:line` k ověření |
|-------|----------|-------------|-------------------------------|
| **F1** nechráněná reálná Binance order cesta | Critical | #69 | `execution_engine.py:market_order` (guard `check_live_order_guard` PŘED `client.post("/api/v3/order")`); `runtime_mode.py:83,126`; `tests/test_execution_engine_no_real_order.py` |
| **F2/F3** deploy/process SHA drift + autodeploy | High | #71 | `src/services/deploy_marker.py`; `bot2/main.py` (write marker); `scripts/hetzner_paper_train_deploy_and_audit.sh` (restart off running-SHA + code-impact + `.deploy_hold` + zero-position gate); `hetzner-fetch-health.yml` (3 SHA identity) |
| **F4** auth bypass při security ON | High | #70 | `dashboard_auth.py:evaluate` (`DASHBOARD_AUTH_DISABLED` ignorován když `security_enabled()`); `tests/test_dashboard_auth.py` |
| **F5** authoritative pipeline tichý no-op | High | #70 | `paper_close_pipeline.py:assert_supported_mode`; `bot2/main.py` (fail-closed boot) |
| **F9** neaktuální audit log | Medium | #70 | `AUDIT_CHANGES_LOG.md` (Round-2 sekce) |

**Kontext ještě staršího incidentu (kolo 2.5):** autodeploy timer nasadil PR5 (#66) s fail-closed auth jako výchozím → dashboard 503 lockout Android appky. Opraveno **ship-dark** (#68): `DASHBOARD_SECURITY_ENABLED` default off = chování před PR5.

**Kompletní řetězec commitů:** #62–#67 (master implementation P0–P2), #68 (ship-dark incident), #69 (F1), #70 (F4/F5/F9), #71 (F2/F3).

---

## 2. Připojení na server (read-only)

Beze změny oproti v2: **`hetzner-fetch-health.yml`** (`workflow_dispatch`) → artefakt `cryptomaster-health-<N>`. **Nově obsahuje** (audit F2/F3) v `deploy_diagnostics.txt` trojici SHA identit: `repo_head_sha` vs `deployed_bot_sha` vs `running_bot_sha` + stav `.deploy_hold`, a `canonical_pipeline_probe.txt` (PR6 shadow). Secrets se netisknou.

---

## 3. Re-verifikační úkoly (uzavřel každý nález, nebo obchází?)

### 3.1 F1 — reálná order cesta (nejvyšší)
- Potvrď, že `market_order` fail-closed vrací `{}` **před** jakýmkoli HTTP, když guard neprojde, a že oba call-sity (`_handle_signal`, exit) jdou přes něj.
- Grep celý repo znovu na reálné order primitivy (`/api/v3/order`, `create_order`, `place_order`, `new_order`, `futures ... order`, `ccxt`) — je `execution_engine` opravdu jediná, a je guardovaná? Existuje jiná (spot/futures) cesta, kterou audit v2 přehlédl?
- Runtime: potvrď z `service_status.txt`/`.env`, že `EXECUTION_ENGINE_ENABLED != 1` a live flagy false. Vyjmenuj přesně, co by se muselo změnit pro live (aby to bylo monitorovatelné).

### 3.2 F2/F3 — deploy integrita
- Z čerstvého snapshotu porovnej `repo_head_sha` vs `deployed_bot_sha` vs `running_bot_sha`. Sedí (žádný drift), nebo je vidět rozjezd?
- Ověř bash logiku restart-decision v `scripts/hetzner_paper_train_deploy_and_audit.sh` pod `set -euo pipefail`: fail-safe default při chybějícím markeru, code-impact filtr (docs-only nerestartuje), zero-position gate. Najdeš cestu, jak by docs-only merge přesto restartoval, nebo jak by se bot zasekl na starém SHA?
- Je autodeploy dostatečně gatovaný, nebo doporučuješ jít dál (root-owned hold + TTL + reason, oddělený dashboard worktree)?

### 3.3 F4/F5
- F4: potvrď, že `security ON + DASHBOARD_AUTH_DISABLED=1` už NEobejde auth (vrací 503/401), a že ship-dark default (security off) je stále otevřený jako dřív.
- F5: potvrď, že `PAPER_CANONICAL_PIPELINE=authoritative` fail-closed odmítne startup, a že off/shadow/unset startují.

### 3.4 Bezpečnost (znovu)
- Přepočítej WR/PF/expectancy z `cache.sqlite` segmentovaně. Dashboard headline neber jako zdroj pravdy.
- Explicitně potvrď (nebo vyvrať) po F1: **žádná runtime cesta nedosáhne reálného order submission.**

---

## 4. Otevřené nálezy (Medium) — k posouzení priorit

| # | Severity | Podstata |
|---|----------|----------|
| **F6** | High/Med | Dashboard get_metrics míchá okna (lifetime count + recent WR + session net); web graf násobí `lifetime_n * recent WR` a počítá FLAT jako loss. **Pozn.: JSON API pro Android je konzistentní** (`recent{}` blok s wins/losses/flats existuje); jde o browser graf + top-level aliasy. |
| **F7** | Med | PF počítán z pct výnosů; při proměnlivé size se pct-PF a USD-PF liší. Vystavit oba + `basis` metadata. |
| **F8** | Med | `mfe_pct/mae_pct` se nepersistují do canonical close → nelze poctivý counterfactual TP/SL test. **Auditor v2 tohle výslovně povolil jako jediný další edge krok.** |
| **F10** | Med | Firewall workflow ověřuje jen UFW listing + localhost health, ne vzdálenou nedostupnost. |
| **F11** | Med | Runtime důkaz single-step `lifetime_n` (P0.2) z plného `close_path_forensics.txt`. |

**Ziskovost (Round-2 verdikt REJECT, potvrď):** recent PF 0,771, 24h PF 0,173, vše TIMEOUT exity, edge ~13–16 bps < náklad 18 bps. `BEAR_TREND` +0,055 vs `BULL_TREND` −0,754. **Bez evidence žádná změna TP/SL/strategie.**

---

## 5. Očekávaný výstup

### 5.1 Re-verifikační tabulka (per nález)
| Nález | Verdikt: **CLOSED / PARTIAL / REOPENED** | Důkaz `file:line`/artefakt | Zbytkové riziko |

### 5.2 Aktualizovaný celkový verdikt
- Strukturální no-real-trading invariant: dá se teď po F1 podepsat? ANO/NE + přesná věta.
- Deploy integrita po F2/F3: APPROVE / CONDITIONAL / REJECT?
- Ostatní oblasti (metrics, dashboard, security, close pipeline shadow).

### 5.3 **Návrh pokračování od auditora** (roadmapa)
Seřaď zbývající práci podle poměru hodnota/riziko a dej doporučené pořadí. Ke každému kroku: **GO / GO-s-podmínkou / NO-GO**, kritéria úspěchu, a zda je bezpečné to dělat autonomně nebo to vyžaduje operátora. Minimálně se vyjádři k:
1. **F8 (MFE/MAE persistence)** — jako první krok k jakémukoli edge rozhodnutí. Jaké přesně jednotky/pole persistovat, aby byl counterfactual poctivý?
2. **F6/F7 (dashboard headline + PF basis)** — jeden headline window; jak migrovat frontend bez rozbití Android kontraktu.
3. **Zapnutí `DASHBOARD_SECURITY_ENABLED=1`** — přesný preflight/canary checklist (token provisioning, non-root user, systemd unit, VPN/HTTPS, rollback který neotevře port).
4. **PR6 Phase B (authoritative close pipeline)** — kritéria shadow úspěchu (≥ N eligible closes, 100% agreement, 0 side-effect writes), rozšíření parity na celý effect plan, a co musí být hotové před cutoverem.
5. **Autodeploy** — nechat s gaty (#71), nebo přejít na plný hold + operator-approval model?
6. **Edge / ziskovost** — offline counterfactual metodika (E1–E4), out-of-sample kritéria (PF ≥ 1,20, expectancy > 0, stabilita napříč okny, žádný symbol netvoří většinu zisku) před jedním vratným PAPER experimentem.

### 5.4 Explicitní bezpečnostní potvrzení
> „Potvrzuji, že v commitu `6f44bd1` žádná runtime cesta nedosáhne reálného order submission" — nebo pojmenuj přesně, co tomu brání.

---

Díky. Runtime read-only přístup přes `hetzner-fetch-health.yml`; hands-on read-only SSH credentials na vyžádání bezpečným kanálem.
