# Externí audit — CryptoMaster HF-Quant 5.0 (kolo 2, po implementaci P0–P2)

**Od:** provozovatel bota
**Předmět:** Nezávislý adversariální bezpečnostní + trading audit + **rozhodnutí auditora**
**Datum:** 17. 7. 2026
**Auditovat @ commit:** `6f33830` (větev `main`)

---

## 0. Absolutní mantinel (nesmí být porušen ani v doporučeních)

**REAL trading = NO-GO.** Nenavrhuj, nezapínej ani netestuj žádnou live-order cestu.
Vše je pouze paper (`TRADING_MODE=paper_train`, live objednávky čtyřnásobně gaté).
- **Nesnižuj simulované náklady** (`PAPER_FEE_PCT` / `PAPER_SLIPPAGE_PCT`) jen aby PF vypadal lépe.
- **Neměň obchodní strategii/edge** (DEV_FADE, TP/SL, EV/confidence prahy, sizing) jako vedlejší efekt.
- **Nikdy netiskni secrets** (SSH klíč, Firebase klíč, tokeny) — všude rediguj.
- Ke každému tvrzení uveď `file:line` nebo konkrétní log/artefakt. „Runtime ověřeno" piš jen po analýze čerstvého serverového artefaktu.

---

## 1. Kontext a co se od minula změnilo

Systém je **paper-trading** bot na Hetzner VPS. Od minulého kola byl proveden **MASTER IMPLEMENTATION PROMPT** — 6 malých, nezávisle reviewovaných, vratných PR (každý prošel adversariálním reviewer-agentem; PR4 navíc android-contract; PR6 navíc trading-safety), plus 1 incident-hotfix.

| PR | Commit | Rozsah | Gate |
|----|--------|--------|------|
| #62 | — | **P1.5** deterministický **dispatch-only** deploy (odstraněn push trigger, `git reset --hard $SHA` s reachability, fail-closed live gate) + reverzibilní teardown standalone V5 služby | reviewer |
| #63 | — | **P2** per-tick log throttle (`market_stream`) + fail-closed **double-flip env guard** (`trading_env_guard.py`, `SIGNAL_INVERT_TEST`+`PAPER_FADE_SIDES` footgun) | reviewer |
| #64 | — | **P2.9+P1.8** kanonický outcome + PnL-units kontrakt (`src/core/trade_metrics_contract.py`), `_calculate_pnl` deleguje outcome (byte-identické, golden-locked), aditivní SQLite migrace | reviewer (200k fuzz) |
| #65 | — | **P1.7** jeden dashboard read-model (`dashboard_read_model.py`), odstraněny mrtvé zdroje (learning_database.sqlite, journalctl, os.system, port 5000), never-500 | reviewer + android-contract |
| #66 | — | **P1.6** dashboard auth + localhost bind + non-root systemd hardening | reviewer |
| #67 | — | **P0.4** kanonická close pipeline (`paper_close_pipeline.py`) v **shadow módu** (idempotentní UPSERT, effect ledger, canonical eligibility) | reviewer + trading-safety |
| #68 | `6f33830` | **Hotfix incidentu** — ship-dark zabezpečení + restore workflow | — |

**Klíčové doplňkové dokumenty v repu (přečti první):**
- `AUDIT_CHANGES_LOG.md` — historie oprav (co → jak ověřeno → co doověřit).
- Commit messages jednotlivých PR (obsahují přesné file:line a rationale).
- Tento dokument.

---

## 2. Připojení na server (žádný přímý lidský shell)

Provoz je řízen výhradně přes **GitHub Actions `workflow_dispatch`** (SSH s pinovaným host-key, credentials v repo secrets — **hodnoty se nikdy netisknou**).
- **Server:** Hetzner VPS, Debian 12, projekt `/opt/cryptomaster`. Bot běží jako služba `cryptomaster.service` (uživatel běhu root; repo vlastní `cryptomaster` uid 999).
- **Autodeploy:** `cryptomaster-autodeploy.timer` (každé 2 h) stahuje `main` a přenasazuje (SHA-change-gated). **Toto je aktivní** a je jádrem incidentu níže.
- **READ-ONLY runtime snapshot:** spusť workflow **`hetzner-fetch-health.yml`** (Actions → Run workflow) → stáhni artefakt `cryptomaster-health-<N>`. Obsahuje: `service_status.txt`, `latest_health.md`, `cache_sqlite_probe.txt`, `close_path_forensics.txt`, `canonical_pipeline_probe.txt` (nový, PR6), `dashboard_metrics.json`, `quota_forensics.txt`, `mfe_distribution.txt`, `restart_forensics.txt`, `deploy_diagnostics.txt`, `trading_metrics.txt`.
- **Hands-on SSH:** vyžádej si dočasné **read-only** credentials bezpečným kanálem (ne zde, ne v plaintextu).

---

## 3. INCIDENT k přezkoumání (kritické)

**Co se stalo:** PR5 (#66) mergnul se zabezpečením (fail-closed Bearer auth + `127.0.0.1` bind) **aktivním jako výchozím**. Autodeploy timer stáhl `main` a dashboard se restartoval do fail-closed režimu → `503 auth_not_configured` bez provisionovaného tokenu → **Android aplikace zamčena**. (Doloženo: dřívější `dashboard_metrics.json = {"degraded":true,"error":"auth_not_configured"}`.)

**Oprava (hotfix #68, ship-dark):** celé zabezpečení je za přepínačem `DASHBOARD_SECURITY_ENABLED` (výchozí **OFF** = bind `0.0.0.0` + bez auth = chování před PR5). Restore workflow `hetzner-restore-dashboard.yml` synchronizoval opravu a restartoval **jen** dashboard.

**Auditorovy otázky k incidentu:**
1. Je ship-dark opravdu behaviorálně neutrální při `DASHBOARD_SECURITY_ENABLED` unset? Existuje kombinace env, kdy je API tiše veřejně otevřené *a zároveň* to čekáš zapnuté? (`src/services/dashboard_auth.py:evaluate` + `security_enabled`)
2. Je poučení „autodeploy stahuje main, takže žádný merge není bezpečný jako neaktivní bez feature-flagu" správně zvnitřněné napříč PR? (Zejména PR6 shadow flag default off.)
3. Byl by lepší návrh nechat autodeploy respektovat „hold" značku? Doporuč reverzibilní mechanismus.

---

## 4. Co runtime doověřit (z čerstvého `hetzner-fetch-health.yml` artefaktu)

### 4.1 Safety (nejvyšší priorita)
- `TRADING_MODE`, `ENABLE_REAL_ORDERS`, `LIVE_TRADING_CONFIRMED`, `PAPER_EXPLORATION_ENABLED`, `live_trading_allowed`.
- systemd drop-iny (`10-paper-only.conf`, `20-/30-*real-trading.conf`, `zz-force-paper-only.conf`) — potvrď, že žádný neaktivuje live.
- **Explicitně potvrď: žádná runtime cesta nedosáhne reálného order submission.** Vyjmenuj přesně které flagy/soubory by se musely změnit pro live (aby byly monitorovatelné).

### 4.2 Close pipeline & učení (P0.2/P0.3/P0.4)
- **P0.2:** každý eligible close = přesně +1 `lifetime_n`; pro stejný `trade_id` žádné dvojité `[PAPER_CANONICAL_LEARNING_UPDATE]`.
- **TIMEOUT_NO_PRICE:** nezvyšuje `lifetime_n` (emituje quarantine/skip).
- **P0.4 shadow:** až operátor zapne `PAPER_CANONICAL_PIPELINE=shadow`, ověř z `canonical_pipeline_probe.txt`, že `[CANONICAL_PIPELINE_SHADOW]` hlásí `agree=true` na reálných closech (kanonická eligibility == legacy). Potvrď, že shadow nezapisuje side-effecty.
- **Nezávisle přepočítej** WR/PF/expectancy z `cache.sqlite` segmentovaně (strana/symbol/režim/hodina/exit_reason/bucket). **Dashboard headline neber jako zdroj pravdy** (i když je teď z read-modelu).

### 4.3 Dashboard/security posture
- Potvrď aktuální bind (`0.0.0.0` vs `127.0.0.1`), zda auth aktivní, `DASHBOARD_SECURITY_ENABLED` stav.
- Ověř never-500: `dashboard_read_model.get_metrics/get_recent_trades` nesmí vyhodit 500 při locked/corrupt DB, non-dict JSON, legacy schéma.
- Android kontrakt: všechny klíče, ISO8601-ms-Z, české statusy (`UČENÍ`/`PŘIPRAVEN`/`VYPNUTO`/`ČEKAT`), side-aware pnl.

---

## 5. Trading edge — poctivá realita k posouzení

Aktuální runtime (`6f33830`, health-526):
- **Lifetime:** n=16 958, PF=0,289, expectancy=−0,096 (historická ztrátová éra).
- **Recent 100:** WR=45 %, PF=**0,771**, net=−0,37 USD → **stále mírně ztrátové**.
- **exit_distribution: timeout=1005, tp=0, sl=0** — **VŠECHNY exity jsou 15min TIMEOUT** (`hold_s=900`). TP/SL se nikdy netriggerují.
- Edge: zachycené ~16 bps (median winner realized) vs simulovaný náklad ~18 bps.

**Auditorovy otázky k edge:**
1. Proč vše končí timeoutem? Jsou TP/SL prahy tak daleko, že se nikdy netrefí, nebo je logika triggeru vadná? (`paper_trade_executor` TP/SL evaluace.)
2. Je edge reálný po nákladech? Přepočítej cost-adjusted expectancy po segmentech.
3. Regime závislost `PAPER_FADE_SIDES=buy_only` experimentu (data z rostoucího režimu — overfitting?).
4. **Doporuč minimální reverzibilní změnu** (bez porušení mantinelu §0), pokud existuje evidence-based cesta k PF > 1. Pokud edge není reálný, řekni to natvrdo.

---

## 6. Očekávaný výstup — **ROZHODNUTÍ AUDITORA**

Písemný report, který KONČÍ explicitním rozhodnutím. Struktura:

### 6.1 Exec summary
- Je systém **bezpečný** (paper-only invariant)? ANO/NE + důkaz.
- Je edge **reálný**? ANO/NE/NEPRŮKAZNÉ.
- Top 5 rizik (severity + `file:line`/artefakt).

### 6.2 Tabulka nálezů
| # | Severity | `file:line` / artefakt | Failure scénář | Minimální vratná oprava |

### 6.3 Verdikt po oblastech (každá: **APPROVE / CONDITIONAL / REJECT** + podmínky)
1. **Deploy integrita** (PR1, dispatch-only, autodeploy interakce)
2. **Safety guardy** (PR2 env guard, live-order absence)
3. **Metrics kontrakt** (PR3, byte-identická close matematika)
4. **Dashboard read-model** (PR4, never-500, Android kontrakt)
5. **Dashboard security** (PR5 + ship-dark hotfix)
6. **Close pipeline** (PR6 shadow; a zda je bezpečné zapnout Phase B)
7. **Trading edge / ziskovost**

### 6.4 Rozhodnutí o otevřených položkách (GO / NO-GO / GO-s-podmínkou)
- **Zapnout `DASHBOARD_SECURITY_ENABLED=1`?** (vyžaduje token provisioning + Android token-flow + VPN/HTTPS) — jaké přesně podmínky musí platit.
- **Zapnout `PAPER_CANONICAL_PIPELINE=shadow`?** (a poté authoritative Phase B) — kritéria pro cutover.
- **Autodeploy timer** — nechat, pozastavit, nebo přidat hold-mechanismus?
- **Edge intervence** — mandát na evidence-first zásah, nebo počkat?

### 6.5 Explicitní bezpečnostní potvrzení
> „Potvrzuji, že v commitu `6f33830` žádná runtime cesta nedosáhne reálného order submission. Pro live by se muselo změnit: [přesný seznam flagů/souborů]."

---

Díky. V případě potřeby runtime přístupu se ozvi kvůli bezpečnému předání read-only credentials.
