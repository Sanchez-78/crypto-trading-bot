# Aktuální provozní stav — jediný index autority

Aktualizováno: 2026-11-18 (C1 uzavřen, kohorta candle-refresh). Při rozporu má tento soubor přednost před staršími
dokumenty; starší dokumenty jsou historický záznam. Kdo mění stav, aktualizuje tento soubor.

## Cíl (operátor, 2026-11-09)

„Imaginární ztráta nevadí, potřebujeme co nejvíce obchodů pro proces učení a metriky,
proč se učení zlepšuje/nezlepšuje.“ Bot je **PAPER only**. Virtuální ztráta není důvod
k zastavení. Cíl WR > 50 % / kladné P/L z `CLAUDE.md` není aktuální měřítko práce.

**Doplněno operátorem 2026-11-09 ~10:00 UTC:** „pokračuj autonomně, cíl P/L+, WR > 50 a
dokonalý a zlepšující se proces učení.“ Výklad agenta: P/L+ a WR > 50 % jsou konečný cíl,
cestou k němu je proces učení; C1 je test, zda učení vůbec nese signál, takže zmrazení
sběru platí dál (operátor C1 nezrušil). Pozor: při TP 35 / SL 25 bps a nákladech 9 bps
je bod zvratu WR ≈ 56,7 % (výhra +26, ztráta −34 bps), takže WR > 50 % samo P/L+ nezaručí.

## Aktivní konfigurace (server `/opt/cryptomaster`, nasazeno souborově, ne z gitu)

| Položka | Hodnota | Zdroj |
|---|---|---|
| Limity průzkumu | 480/den, 30/h, cooldown 300 s, min. modelovaný net −25 bps | drop-in `zzzzzzzzzz-probe-volume.conf` |
| Symboly | všech 7 (blacklist prázdný) | tamtéž |
| CONTROL podíl | 1,0 (sběr: adaptivní odmítání vypnuto, odhad se loguje) | drop-in `zzzzzzzzzzz-learning-collect.conf` |
| TP/SL, náklady | beze změny (35/25 bps, fee 8 + slippage 1 bps) | `/opt/cryptomaster/.env`, overlay |
| Stupně S2/S3 | **zrušeny**, stage timer a skripty odstraněny | — |

„Všichni kandidáti“ znamená jen bez adaptivního odmítnutí; pacing, risk, kvóty, data a
generátory dál určují, co vstoupí.

## Experiment C1 — UZAVŘEN 2026-11-16 17:48 UTC

- **Verdikt `CONTRARIAN_NOT_SHOWN`** (předregistrace `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`,
  dodatek 1/1b/1c). N = 1 000 (500/500), 19 šestihodinových bloků, 7,43 dne.
  C1 lift −1,58 bps, Welch 95% [−4,47; +1,31], blokový bootstrap [−4,34; +1,92].
  Protisměrné pořadí se na nových datech **nereplikovalo**; historické „záporné řazení“
  (ρ = −0,11) tedy nejspíš byl šum. Pro orientaci (ne test): V0 +2,15 [−0,73; +5,04],
  V2 +1,58 — ani přímé učení kladné řazení neprokázalo. C2 se podle runbooku nespouští.
- **Nezávislá reference (převzato 2026-11-18 07:03 UTC agentem, ověřeno):**
  `2026-11-16T17:48:35Z PROVENANCE run=20261116T174717Z manifest_sha256=f7b2345e2065e276dbcb8177ecafdd9dbd5229d78d14a692e50d57ac2ae2538c result_sha256=0d97eb6e837042a786810b11cba9eee150a72d24e681be7064b5833d441f69a9`
  (jediná řádka; SHA bajtů obou souborů a `result_sha256` v manifestu se shodují; `contract=c1_provenance_v1`,
  cutoff a run ID sedí; 1 000 unikátních ID). Kopie: `_workspace/c1_freeze_20261116/`.
  Cost review: `_workspace/c1_freeze_20261116/cost_review/review.md` (ziskovost NOT_VERIFIED).
- Od 17. 11. běží plný report MAX_DATA kohorty (`COHORT`, `LEARN_COHORT` ve `verdict.log`).

## Kohorta „candle-refresh“ (od 2026-11-18 07:05:14 UTC)

- Nasazena reviewovaná oprava obnovy svíček (`_workspace/63_…`, review 77 + 81 APPROVE) skriptem
  `deploy_bot_files.sh`: `candle_cache_v1.py` `f3f9370c…`, `p0_8_plus_live_pipeline.py` `f2e4d28d…`,
  drop-in `zzzzzzzzzzzz-candle-refresh.conf` (`PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED=true`).
  Marker: `stage.log` `DEPLOY_candle-refresh APPLIED OK` 07:05:14Z, pid 886991, záloha
  `/opt/cryptomaster_deploy_backups/candle-refresh-20261118T070354Z`. `cohort_start_ms = 1794985514000`.
- Obchody před markerem a po něm **neslučovat**. Vyšší počet obchodů není účinek učení.
- První 4 min: aktivní, PAPER, REAL vypnuto, 0 výjimek, `data_age_ms` 3,5–5,9 s (limit 90 s),
  0× `REJECT_STALE_MARKET_DATA` (předtím ~42–45 % kandidátů), 2 vstupy.
- Konfigurace sběru (limity, cooldown, CONTROL 1,0) beze změny.
- 2026-11-19: stale odmítnutí ~45 % → 0–5 %, přijatých kandidátů ~2×, vstupů beze změny
  (~118 / 12 h). Vázající je natvrdo `max_open_per_bucket = 2` v `paper_trade_executor`.
  `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET` (1–7, výchozí 2, platí **jen** pro `P0_8_PLUS_EVIDENCE_COLLECTION`).

## Kohorta „explore-bucket-cap“ (od 2026-11-23 07:45:02 UTC)

- Nasazen strop průzkumného bucketu 7 (kód + artefakt APPROVE 2026-11-19, nasazovací krok APPROVE
  `_workspace/2026-11-23_codex_review_bucket_cap_deploy_step.md`). Executor `a39d4f4c…` (preimage
  `5b0b15cc…`), drop-in `zzzzzzzzzzzzz-explore-bucket-cap.conf` (`PAPER_EXPLORE_MAX_OPEN_PER_BUCKET=7`).
  Nástroj `deploy_bot_files.sh` `64206444…`, starý v `stage_backups/deploy-tools-20261123T072556Z`.
- Marker: `stage.log` `DEPLOY_explore-bucket-cap APPLIED OK` 07:45:02Z, pid 3733858 (restart 07:43:47),
  záloha `/opt/cryptomaster_deploy_backups/explore-bucket-cap-20261123T072609Z`.
  `cohort_start_ms = 1795419902000`.
- Ověřeno hned po nasazení: hash executoru = pin, proces má `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET=7`,
  `TRADING_MODE=paper_train`, REAL příznaky false, 0 tracebacků, žádný `ALERT`.
- **Účinný celkový limit = 100, ne 5** (k `_workspace/2026-11-23_codex_postdeploy_bucket_cap_review.md`):
  server `/opt/cryptomaster/.env:2` `PAPER_MAX_OPEN_POSITIONS=100`. Executor ho načte přes `load_dotenv`
  na ř. 18, před čtením `_MAX_OPEN` na ř. 150 (výchozí hodnota v kódu je 5). Lokální `.env` (5) pro server
  neplatí. Jde o statický důkaz z kódu a souborů na serveru. Proces ho nemá v systemd prostředí, protože
  `.env` se načítá až v procesu. Celkový limit se neměnil.
- **Kontrola 08:16 UTC (read-only, jen kohorta `explore-bucket-cap`):**
  - 3 souběžně otevřené pozice v `P0_8_PLUS_EVIDENCE_COLLECTION` (dříve strop 2), 0× `max_open_per_bucket`,
    0 tracebacků;
  - v okně journalu (~16 min) 5× `P0_8_PLUS_LIVE_OPEN`, 5× `PAPER_ENTRY`;
  - uzavřené obchody s `entry_ts ≥ marker`: n = 5, 1 výhra, Σ −0,0715 USD. Vzorek je pro jakýkoli závěr
    příliš malý.
  - Důvody v journalu: `REJECT_ECON_BAD_ENTRY` ~48 tis. řádků za 16 min (zdroj logovací záplavy, ne
    odmítnutí kvůli stropu), dále `REJECT_PAPER_LEARNING` 6× a `REJECT_RISK_DENIED` 2×.
- Obchody před markerem a po něm **neslučovat** (ani s `candle-refresh`). Vyšší počet obchodů není
  účinek učení ani důkaz edge.
- Rollback: vrátit executor `5b0b15cc…` a odstranit drop-in ze zálohy. Snížení stropu otevřené pozice
  nezavře; další vstupy do bucketu se odmítají, dokud počet neklesne.

## Kohorta „econ-bad-log-limit“ (od 2026-11-23 11:54:37 UTC; změna observability, ne strategie)

- Nasazeno omezení detailních výpisů `REJECT_ECON_BAD_ENTRY`:
  - kód APPROVE: `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md`;
  - nasazovací krok APPROVE: `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_deploy_step_d6d8.md`;
  - runbook: `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`.
- RDE `95e499e7…` (preimage `4a46037b…`), drop-in `zzzzzzzzzzzzzz-econ-bad-log-limit.conf`
  (`RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true`). Marker: `stage.log` `DEPLOY_econ-bad-log-limit APPLIED OK`
  11:54:37Z, pid 3840326 (restart 11:53:21), záloha
  `/opt/cryptomaster_deploy_backups/econ-bad-log-limit-20261123T115315Z`.
- **Restart proběhl se 2 otevřenými PAPER pozicemi** na výslovný pokyn operátora („proveď vše i tak“),
  protože se pozice při stropu 7 otevírají nepřetržitě:
  - dvě předchozí čekání skončila `SKIPPED open=4` a `open=2`;
  - nástroj `deploy_bot_files.sh` `3bb51c5e…` (commit `ff10f96`) dostal výslovné povolení
    `ALLOW_OPEN_POSITIONS=1`, které se zaloguje (`OPEN_POSITIONS_ALLOWED open=2`); výchozí chování se
    nemění;
  - po restartu `[PAPER_STATE_LOAD] open_positions=2` a `[PAPER_STATE_RECONCILE_SUMMARY] loaded=2 … alive=2`,
    takže se nic neztratilo ani nezavřelo dvakrát;
  - to dokládá jen tento konkrétní restart, ne obecnou bezpečnost povolení;
  - dodatečné review: A1 (kontrola jen `len(json)`) a R1 (validátor přijal pozici bez směru, velikosti
    a TP/SL, kterou loader doplní, chybějící směr na `BUY`) jsou opravené v `deploy_env_check.py
    positions`. Validátor teď přijme jen záznamy, u kterých loader nedoplní ani nezmění žádné
    ekonomicky významné pole; test to ověřuje proti skutečnému loaderu. Nová verze nástroje se na
    server instaluje až po schválení re-review.
  - **Meze povolení (platí při každém dalším použití):**
    - uzavření přerušené restartem před potvrzením v žurnálu proběhne až po restartu, později a za
      jinou cenu;
    - pokud restart přeruší uzavření po zahájení neidempotentních hooků, automatické opakování se
      odmítne. Start pak může skončit stavem, který vyžaduje ruční rekonciliaci
      (`paper_trade_executor.py:3362–3404`);
    - rollback nasazení restartuje službu znovu s otevřenými pozicemi;
    - při změně `paper_trade_executor.py` nebo formátu stavu pozic musí review ověřit kompatibilitu
      nového **i** vraceného kódu se stavem otevřených pozic; `APPLIED OK` ji nedokazuje;
    - po restartu ověřit `[PAPER_STATE_LOAD]` proti poslednímu stavu před vypnutím se zohledněním
      close zapsaných v žurnálu; samotné srovnání dvou počtů za běhu důkazem není.
- Ihned po nasazení:
  - hash a prostředí sedí (`paper_train`, oba REAL `false`, příznak `true`), 0 tracebacků;
  - první souhrn `seq=1`: 1 360 odmítnutí za 61 s, z toho 1 359 detailů potlačeno.
- **Post-check podle runbooku (12:11 UTC, 10min okno; `_workspace/econ_bad_deploy_20261123/postcheck_journal_20261123.txt`): všech 5 kritérií PASS.**
  1. `MainPID` 3840326 = marker a nezměnil se. Journal pokrývá celý čas od restartu, 0 tracebacků.
  2. Souhrny `seq` 8 → 17 (Δsince_s = 547 s): N = 15 592 odmítnutí, S = 15 574 potlačeno,
     N − S = 18 ≤ 17 × 9; sazba **1 710/min** (výchozí 1 744/min, stejný řád).
  3. Detailní výpisy: 20 trace + 20 print za 10 min (výchozí 17 444 každý; mez 187).
  4. `seq` souvisle 8–17, bez mezer.
  5. Kontext: 2× `PAPER_ENTRY`, 2× `P0_8_PLUS_LIVE_OPEN`.
- **Naměřený účinek:**
  - řádky 153 824 → 115 358 (**−25,0 %**) a bajty textu 19,43 → 11,77 MB (**−39,4 %**) za 10 min;
  - retence ~15 → **~22,7 min** (první záznam 11:48:43 při měření 12:11:25; journald na limitu 100 MB).
  - Dál převládají čtyři výpisy každého vyhodnocení signálu (`EV=…`, `coherence[…]`,
    `SCORE_THRESHOLD`, `RDE[…]`). Delší retence by vyžadovala jejich omezení, což je samostatná změna.

## Dashboard (2026-11-19)

- `/api/dashboard/readiness` vrací `status=paper_only` (nasazeno 14:00 UTC skriptem
  `deploy_dashboard_readiness.sh`, záloha `/opt/cryptomaster_deploy_backups/dashboard-readiness-20261119T140027Z`).
  Ustala minutová chyba `[METRICS_COLLECTION_ERROR] Permission denied: .env`. Profil API je veřejný
  (bez tokenu), nasazení ho nezměnilo. Bot nebyl restartován.
- **Viditelnost terminálního backlogu outboxu nasazena 2026-11-19 14:15:30 UTC** (`deploy_bot_files.sh`
  `aa73c519…`, `DEPLOY_outbox-visibility APPLIED OK`, záloha
  `/opt/cryptomaster_deploy_backups/outbox-visibility-20261119T141039Z`, bot restartován, PID 1634146,
  bez drop-inu; marker kohorty). Živé hashe = piny. Read-only stav outboxu 2026-11-23: **6 191 terminálních
  řádků** (červen–29. 8.), 0 přehratelných, nic nového. Worker loguje jen při startu a změně, takže od
  startu nic dalšího nelogoval. Startovní řádka `[V5_BRIDGE_OUTBOX_TERMINAL]` je NOT_VERIFIED, protože
  journal se mezitím přepsal.
- **Provozní nález 2026-11-23:** journal `cryptomaster` drží jen asi 15 minut, bot zapisuje kolem 230 tis.
  řádků za hodinu (hlavně `on_price`). Starší důkazy z journalu nejsou k dispozici. Měření proto stavět
  na `stage.log`, `verdict.log` a DB, ne na journalu. Snížení logování je samostatná změna, zatím
  nenavržená.
- Historický experiment ADAPTIVE vs CONTROL (do 9. 11.): `SELECTION_EFFECT_NOT_SHOWN`,
  uzavřen — při CONTROL = 1 nová ramena nevznikají.

## Měření (server, nezávislé na sezení Claude)

- `cryptomaster-research-eval.timer` 05:47 a 17:47 UTC → `/opt/cryptomaster_research/run_eval.sh`.
- Každý běh: `reports/<UTC run ID>/` s `manifest.json` (SHA snapshotu, kódu, env),
  `report.*` (epocha do cutoffu), `replay.*`; zámek proti souběžným během.
- `verdict.log`: řádky `EPOCH`, `LEARN_EPOCH` (obojí jen do cutoffu C1), `REPLAY`
  (exploratorní jen do cutoffu + stav C1) a `COHORT_BLIND` (jen počty čerstvých obchodů).
  Plný report MAX_DATA kohorty (`cohort/`) až po zmrazeném výsledku C1.
- `STATUS` = poslední výsledek (`OK` / `FAILED:<krok>`); selhání spustí
  `cryptomaster-research-alert.service` → `ALERT` soubor a journal (priorita err).
- `prereg_result.json` (neměnný) vzniká uvnitř běhu při prvním závěrečném verdiktu C1;
  když pak selže zbytek běhu, výsledek už zmrazený je (vyhodnocení proběhlo právě jednou).
  Souběžný běh odmítnutý zámkem skončí tiše (exit 0).
- `cryptomaster-research-funnel.service` (od 9. 11.): čte journal bota a ukládá hodinové
  počty fáze funnelu (kandidáti P0.8+ podle kódu, vstupy, pacing, skipy) do
  `funnel/YYYYMMDD.jsonl`; bez cen a výsledků (bezpečné pro slepou fázi). Řádek `FUNNEL`
  ve `verdict.log` = posledních 12 h. Důvod: journal bota drží jen ~15 min (objem logu).
- **Mezera:** žádný kanál, který by operátora upozornil bez sezení Claude (otázka 4 níže).
- **Ztráta kandidátů od 07:30 UTC 2026-11-09:** `REJECT_STALE_MARKET_DATA` 118× vs. 87
  vstupů za 07:30–10:16 (předchozí 2 dny 0×), od začátku populace C1. Příčina ověřena:
  fáze 60s plánovače po restartu (:44–:50 místo :15–:19) + přeskočený refresh cache svíček.
  **Během C1 bota nerestartovat** — nová fáze by náhodně změnila podíl ztracených kandidátů.
  Oprava hotová lokálně (Codex, `_workspace/63_codex_candle_refresh_fix.md`, přesný diff
  `_workspace/candle_refresh_20261109/task.diff`): `candle_cache_v1` obnovuje dokončené
  svíčky jednou za UTC minutu za příznakem `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED`
  (výchozí vypnuto) + `data_age_ms` v řádku `[P0_8_PLUS_LIVE]`. Kontrola agentem 9. 11.:
  112 cílených testů prošlo i při nezávislém opakování, mutace zachyceny, diff přečten
  (výpočet `data_age_ms` nemůže selhat — router stejný rozdíl počítá dřív). **Nenasazeno.**
  Po zmrazeném výsledku C1: nezávislé review přesného diffu opravy **i** rozšíření allowlistu
  `deploy_bot_files.sh` (připraveno lokálně 2026-11-11: oba moduly, příznak a striktní
  validace `true`/`false`; server má zatím starou verzi `52d50fe7…`), zadání
  `docs/codex_prompts/INDEPENDENT_REVIEW_CANDLE_REFRESH_PHASE_FIX_2026-11-11.md` → nasazení
  novým skriptem jako **nová kohorta** (marker v `stage.log`) → ověřit `data_age_ms` < 90 000,
  nejvýš 1 fetch za symbol a minutu a pokles `REJECT_STALE_MARKET_DATA` bez závislosti na fázi
  (legitimní stale při výpadku upstreamu zůstává). Postup dne zmrazení:
  `docs/remediation/C1_FREEZE_DAY_RUNBOOK_2026-11-11.md`; C2 jen podle
  `docs/remediation/C2_REPLICATION_DRAFT_2026-11-11.md`. Serverová
  verze `candle_cache_v1.py` před opravou: SHA-256 začíná `23a9068111012aac`.
  Detail příčiny: `_workspace/62_stale_market_data_rejections_since_restart.md`.
- Záloha `/opt/cryptomaster_deploy_backups/audit-20260923` (8,4 GB) smazána na pokyn
  operátora 2026-11-09 ~10:35 UTC → disk 60 %.
- **Disk 2026-11-09 (opraveno 10:18 UTC):** růst ~3,6 GiB/den způsobuje `/var/log/syslog`
  (rsyslog kopíruje ~13 000 řádků/min stdout bota; pravidlo `30-cryptomaster-stop.conf`
  je mrtvé, bot loguje jako `python3`), ne `shadow_excursion.sqlite` (~50 MiB/den).
  Zásah: zkomprimován uzavřený `syslog.1` a z `/etc/logrotate.d/rsyslog` odstraněno
  `delaycompress` (záloha `/root/logrotate.d-rsyslog.bak-20261109`) → 88 % → 83 %,
  minimum volného místa před denní rotací ~4 GiB. Syslog bota záměrně NEvypnut: journald
  je jen v RAM, takže `/var/log/syslog*` je jediná trvalá historie logů bota.
  Detail: `_workspace/61_disk_shadow_excursion_growth_risk.md` (errata nahoře).

## Povolené akce agenta

Operátor opakovaně autorizoval autonomní práci („pokračuj autonomně“, „po automatické
analýze nasaď vše potřebné“, „pracuj autonomně“, 26. 10.–9. 11.) a commit/push po každém
commitu. **2026-11-09 ~09:55 UTC operátor potvrdil: „dělej vše bez ptaní“.** Rozsah níže
tím platí bez dalších dotazů; bezpečnostní hranice (sekce „Vyžaduje operátora“, PAPER only)
zůstávají:

- Čtení serveru (SSH read-only), výpočty, reporty, dokumentace, commit a push.
- PAPER změny výzkumné části (`/opt/cryptomaster_research`) s testy.
- PAPER změny bota jen přes `deploy/research_eval/deploy_bot_files.sh` (allowlist,
  zámek, záloha, rollback) a **po nezávislém review přesného diffu**, pokud mění
  rozhodovací politiku, protokol experimentu nebo nasazovací skripty.

**Zmrazení sběru během C1:** skončilo 2026-11-16 (C1 uzavřen). Každá další změna sběru se
nasazuje jako nová kohorta s markerem v `stage.log`, ne současně s jinou změnou.

**Reset P/L / DB / Firebase:** operátor 2026-11-09 povolil („pokud je třeba reset PL nebo
firebase atd., proveď“). Během C1 se reset **neprovádí**: C1 se vyhodnocuje z `closed_trades`
v `cache.sqlite` po cutoffu a reset by test zničil. Použít až po zmrazeném výsledku C1, a to jen
pokud nová fáze potřebuje čistou epochu (předtím záloha DB).

**Nový zdroj signálu:** funding carry uzavřen (audit v9 NO-GO). Offline screen dat z futures
(OI, long/short, taker ratio, funding, taker imbalance, BTC→alty) na horizontu bota
zadán Codexu (`docs/codex_prompts/CODEX_NEW_SIGNAL_SOURCE_SCREEN_2026-11-09.md`,
předregistrace TRAIN/TEST/HOLDOUT). **Výsledek 2026-11-10: všech 7 NO_EDGE** (hrubě 0–1 bps
vs. náklad 9 bps; `RESEARCH_FUTURES_FLOW_FINDINGS.md`). Celkem 17 rodin bez edge; levné
veřejné zdroje na horizontu bota jsou vyčerpané. P/L+ vyžaduje rozhodnutí operátora (jiný
trh, jiná nákladová struktura nebo jiný cíl); agent do té doby nestaví nové strategie.
Pozor (review 2026-11-10): „vyčerpané“ je přehnané. NO_EDGE platí jen pro testované
konfigurace, 17 rodin nejsou nezávislé důkazy a report 64 přehlíží chybějící futures data
z 2026-10-28. Errata a audit skutečných nákladů (fee na stranu vs. round trip, spread ve fill
ceně) má Codex v `CODEX_POST_C1_COST_AND_LEARNING_REVIEW_2026-11-10.md`.
**Provedeno agentem 2026-11-10** (`_workspace/65_codex_cost_and_learning_review.md`): spread se
dvakrát nepočítá. Paper náklady jsou naopak **podhodnocené**: výstup se plní na mid (chybí půl
spreadu) a 8 bps je za celý obchod (4 na stranu), zatímco spot VIP0 má 10 bps na stranu a futures
5 bps taker. Shorty nad spotovými cenami nemají reálný produkt (marže/futures). Produkční
výpočty zatím beze změny. Po C1 se oprava cache nasadí jako **nová kohorta** a replikace
proběhne jen při CONTRARIAN_CONFIRMED (osnova v reportu 65).

**Původ výsledku C1 (2026-11-10):** offline nástroj `cost_and_learning_review.py` přijme
skutečný C1 jen s manifestem `c1_provenance_v1` zapsaným při zmrazení. Producer je
připravený lokálně (`learner_replay_report.py` + `run_eval.sh --run-id`, testy, 6/6 mutací)
a čeká na audit Codexu (`CODEX_AUDIT_C1_PROVENANCE_PRODUCER_2026-11-10.md`). **Nasadit do
`/opt/cryptomaster_research` před prvním možným zmrazením 2026-11-16 17:47 UTC**, jinak zůstane
skutečný C1 v nástroji NOT_VERIFIED. Bot se nerestartuje, evaluator ani kritéria se nemění.
Audit (`_workspace/70_…`, provedl Claude jako autor, tedy nezávislý není) našel A1 (hash se
mohl ztratit při selhání pozdějšího kroku běhu) a A2 (zmrazení bez run ID). Obojí je
opraveno. Při zmrazení se do `verdict.log` hned zapíše řádka
`PROVENANCE run=… manifest_sha256=… result_sha256=…`, ještě před markerem výsledku, a
agent ji pak přenese sem jako důvěryhodnou referenci. Nezávislé review 71 (Codex) našlo
B1–B3 (alias cesty logu a výsledku, falešná řádka přes run ID, chybějící `fsync`), opraveno
v reportu 72. Review 73 našlo alias přes hardlink, opraveno (`samefile` a zápis přes
nový inode, dodatek reportu 72). Review 75: APPROVE. **Nasazeno 2026-11-11 09:00 UTC**
po syntetickém preflightu na serveru (vše PASS), záloha
`stage_backups/c1-provenance-20261111T090057Z`, ověřovací běh OK (PENDING, bez řádky
PROVENANCE). Detail a rollback: `_workspace/76_c1_provenance_deploy_20261111.md`.
Do `OPERATING_STATE` přenášet jen řádku `PROVENANCE`, jejíž oba hashe odpovídají existujícímu
výsledku i manifestu.

## Vyžaduje operátora

Nová hypotéza mimo předregistraci, změna cíle, trvalá změna politiky učení, cokoli
mimo PAPER, změna TP/SL nebo nákladů.

## Nahrazené / historické dokumenty

| Dokument | Stav |
|---|---|
| `docs/remediation/AUTONOMOUS_LEARNING_LOOP_2026-10-26.md` | S1→S2→S3 zrušeno 9. 11. |
| `_workspace/autonomy/2026-11-09_S2.md` | historický; S2 vrácen na S1 o 7 min později |
| `_workspace/58_why_bot_does_not_improve.md` | část závěrů opravena (viz Errata v souboru) |
| `CLAUDE.md` — CORE ARCHITECTURE, autonomní 30min smyčka do WR > 50 % | zastaralé pro současnou PAPER cestu |
| `AGENTS.md` — zákaz commit/deploy | psáno pro Codex/externí agenty; uplatnění na Claude je výklad agenta (čeká na potvrzení) |

## Výchozí odpovědi na otevřené otázky auditu (agent; platí na základě „dělej vše bez ptaní“)

1. Hlavní výsledek: více kvalitně atribuovaných vzorků + měření, zda pořadí učení
   předpovídá výsledek. Net na obchod je sekundární.
2. C1 = jednorázový test s pevným koncem (dodatek 1), celková chybovost 5 %.
3. Po potvrzení jen omezená replikační PAPER fáze po review; trvalou změnu schvaluje operátor.
4. Alert mimo sezení: **neřešeno** — potřeba kanál od operátora (e-mail/Telegram/jiný).
5. Autorita: `manifest.json` každého běhu + `POSTIMAGE.sha256` každého deploye.
6. 9 bps zůstává primární měřítko učení; realistické poplatky (15–20 bps) vykazovat zvlášť.
7. Zdroje: sledovat disk (60 % po opravě rotace syslogu a smazání zálohy 2026-11-09), RAM a Firebase kvóty při vyšším objemu.
