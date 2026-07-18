# Externí audit — CryptoMaster HF-Quant 5.0 (kolo 5: re-verifikace Round-4 + ROZHODNUTÍ o edge / no-edge)

**Od:** provozovatel bota
**Předmět:** Potvrdit uzavření Round-4 nálezů + vydat **GO / NO-GO rozhodnutí** o dalším směřování strategie po zjištění záporného očekávání a zablokovaného E1–E4
**Datum:** 18. 7. 2026
**Auditovat @ commit:** `1eba962` (větev `main`) + otevřený **PR #79** (F2/F3-r3)

---

## 0. Absolutní mantinel (beze změny)

**REAL trading = NO-GO.** Vše paper (`TRADING_MODE=paper_train`, live objednávky čtyřnásobně gaté). Nesnižuj náklady, neměň edge jako vedlejší efekt, netiskni secrets, ke každému tvrzení `file:line` / artefakt. „Runtime ověřeno" jen po analýze čerstvého serverového artefaktu.

---

## 1. Co se od kola 4 změnilo

| Nález | Round-4 verdikt | Round-5 stav | PR | Gate |
|-------|-----------------|--------------|----|----|
| **F10** firewall | injection (HIGH) | anti-injection validace (enum + `ipaddress` + port allowlist) PŘED SSH; fail-closed rollback (nikdy `ufw delete deny`); default port **5000** (5001 = LIVE API se nefirewalluje) | **#77 merged** | reviewer APPROVE (LOW) + trading-safety SAFE |
| **F2/F3** reset-before-gate | REJECT | `git reset --hard` a restart až PO hold + zero-position gate; rozhodnutí z fetchnutých SHA před mutací working tree; docs-only sync zůstává povolený | **#79 open** | reviewer gate **probíhá**; `bash -n` OK, 22/22 statických testů |
| **health CSV** | (nový) | read-only dump celé `closed_trades` do CSV artefaktu pro offline E1–E4 | **#78 merged** | self-verified (read-only, non-trading) |
| **Pauza obchodování** | (nová akce) | `PAPER_SYMBOL_BLACKLIST` = všech 7 symbolů → `signal_generator.py:682` `return` pro každý symbol → 0 nových vstupů; služba + dashboard 5001 běží | run #2 success | auto-rollback armed |

**Řetězec:** …#75 (F10) → #76 (:5000 fix) → **#77 (F10-r2)** → **#78 (health CSV)** → **#79 (F2/F3-r3, open)**.

---

## 2. Připojení na server (read-only)

**`hetzner-fetch-health.yml`** (`workflow_dispatch`) → artefakt `cryptomaster-health-<N>`. **Nově (#78)** obsahuje `closed_trades.csv` — plný řádkový dump (`SELECT *`, mode=ro) pro offline výpočet PF / walk-forward mimo dashboard. Poslední snapshot: **`health-536`** (server @ `1eba962`, čas 05:24–05:25 UTC).

---

## 3. Re-verifikační úkoly

1. **F10-r2 (#77):** validace vstupů běží PŘED SSH krokem (žádný `if:` guard, `set -eo pipefail` → `sys.exit(1)` shodí job)? `ip_network` + metachar blocklist skutečně blokují breakout? Rollback nikdy neotevře veřejný port? Default `ports=5000` (5001 nedotčen)?
2. **F2/F3-r3 (#79):** jediný reálný `git reset --hard "$REMOTE_NAME/$BRANCH_NAME"` (řádek ~300) je AŽ ZA hold gate (`.deploy_hold`, ~246) i zero-position gate (`paper_open_positions.json`, ~275)? Žádná jiná cesta nemutuje working tree (checkout/pull/merge/clean) před gaty? Pro **code-change** hold i pozice revokují `adopt_code` (reset) i `restart_needed`; pro **docs-only** se sync povolí bez restartu — potvrď obě větve. Fail-closed zachováno (missing READY → restart; UNKNOWN pozice → refuse)?
3. **health CSV (#78):** dump je opravdu read-only (`mode=ro`), žádný zápis/restart, žádné secrets v `closed_trades`?

---

## 4. Runtime důkazy k validaci (snapshot `health-536`, server `1eba962`)

- **F2/F3 mechanismus BĚŽÍ:** `repo_head=ready=boot=1a72e42`, `deployed_bot_sha=5a26731` (lag — marker se píše až po is-active+READY konvergenci), `deploy_hold: absent`, repo owner `cryptomaster uid 999` (non-root). Autodeploy u #77/#78 (workflow-only) korektně **„restart skipped: docs/workflow-only change (no code impact)"** — code-impact gate funguje. **Ověř nezávisle.**
- **Pauza potvrzena:** health.md „Trading mode: neutral", „No PAPER_TRAIN_ENTRY events", 0 nových vstupů po restartu z blacklistu. `open_positions=0`.
- **F1 sign-off:** žádná `EXECUTION_ENGINE` aktivita; `live_real allowed: false`. **Potvrď proti čerstvému artefaktu.**

---

## 5. JÁDRO KOLA 5 — výkon je záporný a E1–E4 je zablokovaný

### 5.1 Metriky (health-536, `closed_trades.csv`, 1021 řádků lokálního okna; lifetime čítač 17 036)

- **100 % obchodů končí `TIMEOUT`** — TP (~54 bps) ani SL se nikdy netrefí; pozice drží do max věku a zavře na malém +/−.
- **Celé okno (sloupec `win`, 1021):** WR **31,0 %** (316/1021), net `pnl_usd` **−0,9164**.
- **Segment podle režimu:** `BULL_TREND` 764 obch. WR **25,8 %** (−0,7645) · `BEAR_TREND` 257 obch. WR **46,3 %** (−0,152). → fade proti UPtrendu je hlavní krvácení.
- **Segment podle symbolu (net):** ETH 385/28,3 % (−0,2918) · ADA 248/45,6 % (−0,2348) · DOT 58/27,6 % · SOL 157/40,1 % · **BNB 72/0,0 %** · **XRP 65/1,5 %** · BTC 36/38,9 % (−0,0059).
- **Čistá pod-množina se `pnl_pct` (162 nových řádků):** WIN 95 / LOSS 66 / FLAT 1; WR 58,6 %; gross_profit 15,116 % / gross_loss 16,361 % → **PF 0,924**; net −1,246 %; **−0,77 bps/obchod hrubě → −18,77 bps/obchod po 18 bps nákladech**.
- **Poslední okna (dashboard read model):** 24h n=19 WR 52,6 % **PF 0,429** · 7d n=30 WR 43,3 % **PF 0,266**. Dashboard headline (08:14): WR 38 %, PF 0,54, net −$0,92.

**Závěr provozovatele:** přes ~1000 obchodů (a 17k lifetime) je to **statisticky záporné očekávání, ne šum.** DEV_FADE mean-reversion nemá v aktuálním režimu edge.

### 5.2 Blokující zjištění: excursion data prakticky neexistují

- `mfe_gross_bps`/`mae_gross_bps` má **jen 6/1021 řádků** (F8 populace se teprve rozjela; legacy 859 řádků nemá ani `pnl_pct`, jen `win`/`pnl_usd`).
- **Důsledek:** offline **E1–E4 counterfactual (sweep TP/SL) NELZE spustit** — není intra-trade excursion dráha, na které by se počítalo, kolik obchodů by kandidátní TP/SL trefilo.
- **Catch-22:** pro nasbírání excursion evidence by bot musel dál obchodovat (aby plnil MFE/MAE), ale právě jsme obchodování **pozastavili** (a je ztrátové). Nelze zároveň sbírat data a nekrvácet ze stejné no-edge strategie.

---

## 6. ROZHODNUTÍ AUDITORA — GO / NO-GO

Ke každé polož vydej **GO / GO-S-PODMÍNKOU / NO-GO**, kritéria, a zda smí autonomní agent nebo to vyžaduje operátora.

### 6.1 Jak získat excursion evidenci přes pauzu?
Možnosti: (a) **řízená data-collection fáze** — odblokovat jen nejméně špatné symboly (BTC breakeven / BEAR-favorable) s minimální/nulovou size čistě pro plnění MFE/MAE; (b) implementovat **F8b (1s first-crossing path)** a nechat sbírat; (c) offline rekonstrukce z historických ticků (pozn.: tick historie se neukládá — pravděpodobně nedostupné). **Rozhodni** která cesta, kritéria úspěchu, autonomní vs operátor.

### 6.2 Je F8b (1s directional path) nyní POVINNÝ předpoklad E1–E4?
F8a (globální extrémy + `time_to`) i kdyby byla naplněná, nedává intra-trade crossing sekvenci pro sweep více TP/SL úrovní. **GO na F8b teď?** Pokud ano: potvrď kvóta-safe model (in-memory 1s directional OHLC, persist jednou při close, žádný per-tick Firestore) a schéma.

### 6.3 Osud DEV_FADE strategie
Data: BEAR_TREND 46,3 % vs BULL_TREND 25,8 %; BNB 0/72, XRP 1/65. **Rozhodni:** (a) odložit DEV_FADE úplně dokud není validovaný edge; (b) omezit na `PAPER_FADE_SIDES` / jen BEAR_TREND režim jako zúžený forward-test; (c) něco jiného. Připomínka: **žádná změna TP/SL/timeout/entry/sizing bez E1–E4** — platí to i pro „omezení", nebo je zúžení přípustné jako sběr dat?

### 6.4 F2/F3-r3 (#79) — podepsat?
Po doběhnutí reviewer gate: je reorder gate-before-reset úplný a bez regrese? Stačí to, nebo trváš na plném staging/release modelu (worktree + atomický symlink)?

### 6.5 Autodeploy model
Nechat current gaty (READY restart + code-impact + hold + zero-position + nyní gate-before-reset), nebo přejít na **operator-approval** (timer jen fetch+audit+notify)? Round-3 §4.8 to doporučoval.

### 6.6 Druhý dashboard :5000 (`simple_dashboard.py`)
Redundantní, veřejný, skenovaný (opraven crash #76). Vypnout / bind localhost / ponechat? Vztah k firewall #77 (default 5000).

### 6.7 Carry-over (stále operátor/data-gated)
`DASHBOARD_SECURITY_ENABLED=1` zapnout? `PAPER_CANONICAL_PIPELINE=shadow` → Phase B? (kritéria z v3/v4 §5.1–5.2 beze změny.)

---

## 7. Očekávaný výstup

1. **Re-verifikační tabulka** F10-r2 / F2/F3-r3 / CSV: **CLOSED / PARTIAL / REOPENED** + důkaz.
2. **Rozhodnutí §6.1–6.7:** GO/NO-GO + kritéria + kdo (autonomní/operátor) + pořadí.
3. **Verdikt o strategii:** je racionální DEV_FADE dál forward-testovat, nebo odložit? Za jakých přesných podmínek smí bot znovu otevírat pozice?
4. **Explicitní bezpečnostní potvrzení** pro `1eba962`: lze podepsat *„žádná runtime cesta nedosáhne reálného order submission"*, nebo co chybí?

---

Díky. Runtime read-only přes `hetzner-fetch-health.yml` (nově s `closed_trades.csv`); hands-on read-only SSH na vyžádání bezpečným kanálem.
