# Předání auditorovi — CryptoMaster HF-Quant 5.0

**Od:** provozovatel bota
**Předmět:** Nezávislý bezpečnostní + trading audit (pokračování)
**Datum:** 16. 7. 2026

---

Dobrý den,

předávám vám k nezávislému auditu obchodního bota **CryptoMaster HF-Quant 5.0**. Jde o **paper-trading** systém na Hetzner VPS. Vaším úkolem je adversariálně ověřit korektnost, bezpečnost, validitu obchodní strategie, observabilitu a integritu nasazení, navázat na předchozí kolo auditu a runtime-potvrdit opravy, které jsou zatím jen staticky ověřené.

## Absolutní mantinel
**REAL trading = NO-GO.** Nenavrhujte, nezapínejte ani netestujte žádnou live-order cestu. Vše je pouze paper (`TRADING_MODE=paper_live`, live objednávky čtyřnásobně gaté). Kde to jde, pracujte read-only; jakýkoli zápis/restart musí být vratný a gatovaný. **Nesnižujte simulované náklady jen proto, aby PF vypadal lépe.** Ke každému tvrzení citujte `file:line` nebo konkrétní log/artefakt.

## 1. Co auditovat a odkud začít
Kompletní zadání a rozsah je ve dvou dokumentech v repu na větvi `main` (jsou přiložené k této zprávě):
- **`EXTERNAL_AUDIT_PROMPT.md`** — architektura, model připojení na server, ranked rozsah (safety / edge / learning / quota / dashboard-security / deploy), metoda, požadovaný deliverable.
- **`AUDIT_CHANGES_LOG.md`** — stav dosavadních oprav (co se změnilo → jak ověřeno → co runtime doověřit), otevřené P1/P2, updated required-order.

**Přečtěte oba dokumenty jako první.**

## 2. Repo a přesný commit
```
Repo:          github.com/Sanchez-78/crypto-trading-bot   (public)
Větev:         main
Auditovat @:   c6565c3    (P0 opravy 8750a49 + clamp oprava c6565c3)
```
Klíčové PR tvořící změny: **#57** (P0.1–P0.4 kritické opravy), **#59** (clamp → `paper_live`), **#49** (dashboard headline = rolling okno), **#53/#54** (buy_only experiment), #18–#46 (infra: deploy, learning, quota, git, flood).

## 3. Připojení na server (žádný přímý lidský shell v provozu)
Provoz je řízen výhradně přes **GitHub Actions `workflow_dispatch` workflows** (SSH s pinovaným host-key, credentials v repo secrets — **hodnoty se nikdy netisknou**).
- **Server:** Hetzner VPS, veřejná IP `78.47.2.198`, Debian 12, projekt `/opt/cryptomaster` (+ symlink `/opt/CryptoMaster_srv`). systemd služby běží jako root; repo vlastní uživatel `cryptomaster`.
- **Dashboard/API pro Android:** `http://78.47.2.198:5001/api/dashboard/metrics`.
- **Runtime snapshot (READ-ONLY — takto získáte živá data):** spusťte workflow **`hetzner-fetch-health.yml`** (Actions → Run workflow) → stáhněte artefakt `cryptomaster-health-<N>`. Obsahuje mj.: `service_status.txt`, `edge_analysis.txt`, `cache_sqlite_probe.txt`, `close_path_forensics.txt`, `quota_forensics.txt`, `dashboard_metrics.json`, `restart_forensics.txt`, `mfe_distribution.txt`, `deploy_diagnostics.txt`.
- **Hands-on SSH** (pokud potřebujete): vyžádejte si dočasné **read-only** SSH credentials **bezpečným kanálem** (ne v této zprávě, ne v plaintextu). SSH klíč, Firebase klíč a další secrety nikdy neposílejte nešifrovaně.

## 4. Nejdůležitější — co runtime doověřit (zatím jen staticky opravené)
Předchozí kolo potvrdilo staticky opravené **P0.1** (`.env` už nepřepisuje systemd), **P0.2** (jeden close se neučí 2×; sjednocený `get_learner()` singleton + `trade_id` dedupe + TIMEOUT_NO_PRICE quarantine), **P0.3** (segmentové metriky parsují 6-prvkové tuple). **Runtime potvrzení stále chybí** — po ≥ několika eligible closes po deployi z 16:42 UTC ověřte z čerstvého `close_path_forensics.txt` + `cache_sqlite_probe.txt`:
1. **P0.2:** každý eligible close = **přesně +1** `lifetime_n`; pro stejný `trade_id` nesmí být dvě `[PAPER_CANONICAL_LEARNING_UPDATE]`.
2. **TIMEOUT_NO_PRICE:** emituje `[LEARNING_RECORD_CLOSE_QUARANTINE]` / `[LEARNING_RECORD_CLOSE_SKIP]` a **nezvyšuje** `lifetime_n`.
3. **P0.3:** segmentové cooldowny se u ztrátových `symbol+regime+side` skutečně aktivují.
4. **Nezávisle přepočítejte** WR / PF / expectancy z `cache.sqlite` (segmentovaně dle strany/symbolu/režimu/hodiny). **Dashboard headline nepovažujte za zdroj pravdy.**
5. **Safety runtime check:** potvrďte `live_trading_allowed=false` a že `.env` + systemd drop-ins (zejména `20-/30-*real-trading.conf`) neobsahují live flagy; ověřte, zda ještě existuje/běží stará služba `cryptomaster-v5-paper`.

## 5. Otevřené položky (další vlna, dle vašeho předchozího nálezu)
P0.4 zbytek (jeden atomický `persist_closed_paper_trade()` handler), P1.5 (odstranit V5 službu z deploye + deterministický `git reset --hard $SHA`), P1.6 (dashboard běží jako root, `0.0.0.0:5001`, bez auth — **High**), P1.7 (`/enhanced` čte mrtvou `learning_database.sqlite`), P1.8 (nejednotná definice WIN), P2.9 (PnL jednotky), P2.10 (per-tick debug). Detaily a doporučené opravy jsou v `AUDIT_CHANGES_LOG.md`.

## 6. Kontext strategie
Aktivní reverzibilní experiment `PAPER_FADE_SIDES=buy_only` (od 16. 7. 08:43 UTC): SELL-fady byly anti-edge v uptrendu (−0,23) vs BUY-fady (+0,17). **Vyhodnoťte overfitting/regime riziko** (data z jediného rostoucího režimu). Thin-edge: zachycené DEV_FADE rozpětí ~20 bps ≈ simulovaný náklad ~18 bps → PF ~1,0. Rollback triggery: BUY WR < 58 %, PF nepřekročí ~1,10, nebo bearish režim.

## 7. Očekávaný výstup
Písemný report: exec summary (je to bezpečné? je edge reálný? top 5 rizik), tabulka nálezů (severity / `file:line` nebo artefakt / failure scénář / minimální vratná oprava), trading-edge verdikt (přepočtené PF/WR po segmentech, cost-adjusted expectancy, regime závislost buy_only), security sekce, a **explicitní potvrzení, že žádná runtime cesta nedosáhne reálného order submission** + seznam přesně kterých flagů/souborů by se muselo změnit pro live (aby se daly monitorovat).

Díky. V případě potřeby runtime přístupu se ozvěte kvůli bezpečnému předání credentials.
