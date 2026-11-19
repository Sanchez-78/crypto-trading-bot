# Po-C1 provozní nálezy a náprava (Claude, 2026-11-18)

Zadání: `docs/codex_prompts/CLAUDE_POST_C1_SSH_AUDIT_REMEDIATION_2026-11-18.md`. Podklad: nezávislý
audit `_workspace/2026-11-18_ssh_full_audit.md`. SSH bylo **jen ke čtení** (07:37–07:59 UTC):
žádná instalace, restart, mazání, replay ani změna práv. Lokální změny zůstávají v pracovním
stromu k nezávislému review, **necommitnuté**. Důkazy jsou v `_workspace/post_c1_remediation_20261118/`.

## Souhrn priorit

| P | Nález | Stav |
|---|---|---|
| P0 | Žádný průlom PAPER-only, C1 původ v pořádku, bot bez pádu | ověřeno znovu (úkol 1) |
| P1 | 6 191 terminálních outbox řádků skrytých metrikou; slepý replay by mohl **přepsat uzavřený obchod** | viditelnost opravena lokálně; rekonciliace jen naplánována (vypnuto) + blocker |
| P2 | Readiness endpoint: import executoru → `load_dotenv` → `.env` zakázán sandboxem; koncept je v procesu dashboardu mrtvý | opraveno lokálně (PAPER-only odpověď, bez importu) |
| P2 | Oprava svíček: nová kohorta | 0 stale od markeru (předtím 35–45 % kandidátů/h); P/L nehodnotitelné (n=6) |
| P2 | Disk: syslog ~4,7 GB/den nekomprimovaně v měřeném okně | rezerva dostatečná, měřit denně |
| P3 | `daily-log-fix-prompt-bot.service` failed (200/CHDIR) | nesouvisí s obchodováním ani alertingem; rozhodnutí operátora |

## Úkol 1 — rozsah a invarianty (SSH read-only, `t1_server_readonly.txt`)

- `cryptomaster.service` active, PID 886991, `NRestarts=0`, od 07:03:59 UTC. Prostředí procesu:
  `TRADING_MODE=paper_train`, `PAPER_ONLY_MODE=true`, `ENABLE_REAL_ORDERS=false`,
  `LIVE_TRADING_CONFIRMED=false`, `REAL_ORDERS_ALLOWED=false`, `STONKFLY_MODE=shadow`,
  `PAPER_LEARNING_CONTROL_FRACTION=1.0`, `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED=true`.
- C1: SHA výsledku `0d97eb6e…69a9` a manifestu `f7b2345e…538c` odpovídají jediné řádce
  `PROVENANCE` (run `20261116T174717Z`). `STATUS` je 05:47:41 OK, `ALERT` neexistuje.
- `stage.log`: `DEPLOY_candle-refresh APPLIED OK` 07:05:14, záloha `candle-refresh-20261118T070354Z`.
- Endpointy (localhost) `/healthz`, `/api/dashboard/metrics` i `/api/dashboard/readiness` vrací 200.
  Otevřené pozice 2. Disk má volno 15,21 GB (61 %).
- **Změny od auditu:** žádné v konfiguraci; jen nové obchody (uzavřené 31 712 → 31 713+).
- Produkční verze čtyř dotčených souborů = lokální výchozí stav (SHA na serveru v
  `server_copies/SERVER_SHA256SUMS`; diff níže obsahuje jen moje změny).

## Úkol 2 — readiness bez přístupu k `.env` (P2)

**Příčina (reprodukováno čtením kódu a unitu):** `dashboard_web.py:437` při importu importuje
`readiness_monitor`, který v paper módu spustil vlákno. Každou minutu volal `get_current_metrics()`,
ta importovala `paper_trade_executor` a jeho modulový `load_dotenv()` (`paper_trade_executor.py:16-29`)
četl `/opt/cryptomaster/.env`. Unit dashboardu má `DynamicUser=true` a
`InaccessiblePaths=-/opt/cryptomaster/.env` (`.env` sám je `644`), takže výsledek byl
`[Errno 13] Permission denied`. Sandbox je správná bezpečnostní hranice a nemění se.

**Proč nestačí oprava přístupu:** dashboard je jiný proces než bot. `_closed_trades_today`
z importovaného executoru by byl vždy prázdný seznam v paměti dashboardu, ne skutečné obchody.
Readiness počítaná v dashboardu tedy byla mrtvá i bez chyby s `.env`.

**Oprava (lokálně):**
- `src/services/readiness_monitor.py`: `get_current_metrics()` vrací `None` s vysvětlením a
  executor neimportuje. Import modulu už nespouští vlákno (`start_monitoring_thread()` zůstává
  pro explicitní volání). Odstraněn nepoužitý `import os`.
- `src/services/dashboard_web.py` `/api/dashboard/readiness`: vrací kompatibilní tvar
  `{"status": "paper_only", "is_ready_for_trading": false, "readiness_score": 0,
  "blocker_reasons": ["paper_only_policy"], "detail": …}`. Nikdy neuvádí `ready=true`.
  Při výjimce dál vrací `service_degraded` (stávající test). `/readiness/status` beze změny.
- **Kompatibilita:** aplikace (`CryptoMaster_app/src/services/dashboardApi.js:87-95`) bere jen pole
  (`Array.isArray(data) ? data : []`), takže objekt z endpointu zahazovala už dnes. Změna jí nevadí.
  `metric_crosscheck.py` porovnává jen klíče, které obě strany mají.

**Testy:** `tests/test_readiness_paper_only.py` (3). Simuluje sandbox: čtení `.env` vyhodí
`PermissionError`, import executoru je zablokovaný, `sqlite3.connect` mimo tmp a `Thread.start`
jsou zakázané a `TRADING_MODE=paper_train`. Ověřuje, že import nemá vedlejší efekty, že readiness
vrací `paper_only` bez čtení `.env` a že metrics endpoint vrací 200 s klíči kontraktu. Fixture
obnovuje i atributy balíčku: první verze testu ovlivňovala pořadí ostatních testů.

## Úkol 3 — terminální Firebase outbox (P1)

**Forenzika (read-only, `t3_outbox_forensics.txt`):** `src/runtime/v5_trade_outbox.sqlite`
obsahuje 6 191 řádků z 2026-06-02 až 2026-08-29 a všechny mají `retry_count` 3 nebo 4
(`OUTBOX_MAX_RETRIES=3`, tj. 0 k replayi). Duplicit (typ, klíč) je 0. Překryv klíčů
`paper_open`∩`paper_close` (1 962) je stejný obchod, ne duplicita. Klíče `paper_*` jsou z 92–96 %
v `closed_trades.trade_id`.

| Třída chyby | Řádků | Význam |
|---|---:|---|
| `must end on doc, not collection` | 639 (learning_update) | chyba kódu opravená 26. 8.; zápis **neproběhl** |
| `'Client' object has no attribute 'set'` | 14 | chyba kódu; zápis **neproběhl** |
| 429 / kvóta | 1 632 | server odmítl; zápis téměř jistě neproběhl |
| `Firebase write failed` (obecná) | 3 906 | **UNKNOWN**: zápis mohl proběhnout před timeoutem |

**Zásadní riziko pro jakýkoli replay:** `firebase_writer.flush_outbox` (`:317-324`) zapisuje
`paper_open` i `paper_close` do **stejného** dokumentu `v5_trades/{trade_id}` přes `set()` bez
`merge`. Slepý replay starého `paper_open` by přepsal uzavřený obchod zpět na otevřený. Úspěšný
zápis (`mark_sent`) řádek maže, takže zbylé řádky nikdy nebyly potvrzené. Kolik dokumentů v cloudu
skutečně chybí, nelze bez čtení cloudu říct.

**Viditelnost (lokálně, bez nového zápisu do Firebase):**
- `outbox.py`: nová `DurableOutbox.backlog_stats()` vrací `replayable_pending`,
  `terminal_unsynced`, `by_type` {replayable, terminal}, `oldest_terminal_created_at/age_s` a
  `max_retries`. Jen agregace, bez ID a payloadů. `pending_count()` se nemění (počítá dál
  `retry_count < max`, klienti `metrics_publisher`, `__init__.get_quota_status`, flush worker).
- `outbox_flush_worker.py`: `[V5_BRIDGE_OUTBOX_TERMINAL]` do logu jednou při startu workeru a pak
  jen při změně počtu (lokální log, typy bez ID). `get_status()` přidává `terminal_unsynced`,
  `terminal_by_type` a `oldest_terminal_age_s`.
- Testy `tests/test_outbox_terminal_backlog.py` (6): terminální řádky jsou viditelné,
  `pending_count()` se nezměnil, ve statistikách nejsou ID, open/close stejného klíče nejsou
  duplicita, reportování nevolá Firebase ani nereplayuje terminální řádky, log při startu je jen
  jednou a chyba DB vede k bezpečnému selhání.

**Rekonciliace: naplánovaná, VYPNUTÁ.** `src/services/v5_legacy_bridge/outbox_reconcile.py`
je čistá funkce `plan(rows, cloud, max_writes)` bez I/O a bez executoru (`ENABLED=False`). Pravidla:
- snapshoty (dashboard/readiness/quota) → `SKIP_SUPERSEDED`;
- neznámý stav cloudu → `UNKNOWN`, žádná akce;
- `paper_open` se nikdy nezapíše přes existující dokument ani při čekajícím close;
- `paper_close` jen když dokument chybí nebo není closed;
- `learning_update` jen merge do existujícího dokumentu;
- pořadí close → learning → open a strop zápisů (`DEFERRED_QUOTA`);
- žádné DELETE ani reset `retry_count`.

Testy: `tests/test_outbox_reconcile_plan.py` (7).

**Blocker zapnutí:**
1. Stav cloudu je nutné přečíst na serveru s credentials bota (~2,1 tis. čtení dokumentů
   `v5_trades/*`, při limitu 50 tis./den proveditelné). To je spuštění kódu na serveru, mimo toto
   zadání.
2. Executor se stropem zápisů a ledgerem potřebuje vlastní review.
3. **Operátor musí potvrdit, zda historii `v5_trades` vůbec někdo čte.** Aplikace bere metriky z
   dashboard API, ne z Firestore. Pokud ne, správnou odpovědí je archivace (záloha DB, ponechat
   evidenci), ne rekonciliace.

## Úkol 4 — kohorta, kapacita, Stonkfly, služba (`t4_*.txt`)

**Kohorty** (`closed_trades.entry_ts` v sekundách, marker `1794985514` = 07:05:14). Výhra =
`win=1`, totéž co `outcome='WIN'`, tj. net > +5 bps podle kontraktu; FLAT je pásmo ±5 bps:

| Skupina | n | WIN | `pnl_usd>0` | Σ pnl_usd | průměr |
|---|---:|---:|---:|---:|---:|
| zmrazení C1 (16. 11. 17:48:35) → marker | 326 | 85 | 121 | −2,0758 | −8,49 bps |
| marker → 07:49 UTC | 6 | 2 | 2 | −0,0582 | −12,93 bps |

Druhá skupina je pro P/L, WR ani účinek učení nepoužitelná. Vyšší propustnost po opravě není
zlepšení učení.

**Kvalita dat po opravě:**
- `REJECT_STALE_MARKET_DATA` od markeru 0 v syslogu i v 30min journalu. Poslední výskyt je z
  06:56:47 ze starého procesu (PID 75073).
- Funnel před opravou (18. 11., 00–06 h): stale 19/42, 57/157, 46/118, 7/19, 31/74, 48/114 a
  8/23 kandidátů, tj. 35–45 %.
- `data_age_ms` (n=11 za 30 min): min 3 484, medián 5 029, max 6 154.
- `[CANDLE_CACHE] fetch failed` 0.
- Počet fetchů na symbol a minutu se do logu nezapisuje. Pokrývá ho simulace v review
  `_workspace/77_independent_candle_refresh_review.md`, na serveru je **NOT_VERIFIED**.

**Stonkfly:** frozen i plastic po 3 signálech za 30 min a 0 `stale=True`. Podle auditu
`readiness_eligible=0`. Jde jen o kontext; při `CONTROL_FRACTION=1.0` neovlivňuje výběr. Kvalitu
a využití kontextu nelze z 30 minut hodnotit.

**Disk (dva body, 07:37:14 a 07:43:52, Δ 398 s):**

| | bod 1 | bod 2 | tempo |
|---|---:|---:|---|
| obsazeno `/` | 23 080 071 168 | 23 102 398 464 | +56 KB/s ≈ 4,8 GB/den hrubě |
| `/var/log/syslog` | 1 198 703 107 | 1 220 489 026 | +54,7 KB/s ≈ 4,7 GB/den (dřív ~3,6 GiB) |
| shadow DB (hlavní soubor) | 11 386 966 016 | stejné | mtime 2026-11-14, bez růstu |
| shadow WAL | 2 224 832 | 2 739 832 | malé, checkpointuje se |

Logrotate drží 4 komprimované syslogy (`syslog.1–4.gz` 0,20–0,37 GB), takže čistý přírůstek je
omezený a denní maximum je asi 5 GB nekomprimovaného syslogu před půlnoční rotací. Volno je
15,2 GB, rezerva při špičce asi 10 GB. **Měření je jen 6,6 minuty v aktivní fázi.** Doporučuji
denní vzorek; mazání evidence bez retenčního protokolu ne.

**`daily-log-fix-prompt-bot.service`:** spouští ho `daily-log-fix-prompt-bot.timer` denně v 08:00,
unit je disabled, `ExecStart=python3 -m src.daily_log_fix_prompt_bot.main`, `User=root`. Selhává
`200/CHDIR`, protože `WorkingDirectory=/root/CryptoMaster_srv/daily_log_fix_prompt_bot` neexistuje
(`/root/CryptoMaster_srv` chybí). Nejde o alerting ani o obchodní cestu, jen o pozůstatek. Doporučuji,
aby operátor vypnul timer, nebo službu opravil, pokud ji chce. Nic jsem neměnil.

## Úkol 5 — validace

- SHA šesti chráněných runtime souborů před a po: **shodné** (`sha_before.txt`, `sha_after.txt`).
- Cílené testy (izolovaný runner): `test_readiness_paper_only`, `test_outbox_terminal_backlog`,
  `test_dashboard_contract_fixes`, `test_sec_01_dashboard_boundary`, `test_v5_legacy_bridge_outbox`
  a `test_phase4d_outbox_flush_worker` dávají **127 PASS, 9 SKIP**, 3× po sobě stabilně. K tomu
  `test_outbox_reconcile_plan` 7 PASS. Bylo ověřeno i opačné pořadí souborů.
- Mutace (`mutation_results.json`, izolovaná kopie): **7/7 zachyceno**.
  - Readiness vrácená na serverovou verzi, readiness hlásí ready, terminální řádky skryté,
    změněný význam `pending_count`, log při každém ticku i odstraněný log při startu.
  - Mutace „backlog_leaks_ids“ ID jen načte a do výstupu nevloží. Zachytil ji jen test bezpečného
    selhání, takže ochrana proti úniku ID není plně ověřená mutací (pokrývá ji test na `repr`).
  - Jednou po obnovení selhal jeden test (název nezaznamenán). Ve 4 dalších bězích se nezopakovalo.
    Nevysvětleno, zřejmě nestabilita harnessu na Windows.
- AST Python 3.12 všech změněných a nových souborů: PASS. Ruff NOT_RUN.
- Pyright hlásí v `dashboard_web.py:348-379` chyby typů v **existujícím** kódu, nesouvisí se změnou.

## Změněné soubory a přesný diff

`_workspace/post_c1_remediation_20261118/remediation.diff` je diff proti serverovým verzím
(`make_diff.py`):

| Soubor | Diff | SHA na serveru (rollback) | Kde běží |
|---|---|---|---|
| `src/services/readiness_monitor.py` | +13 −54 | `854ccfe9…c5d6` | dashboard |
| `src/services/dashboard_web.py` | +15 −11 | `0fdbf5c8…2b60` | dashboard |
| `src/services/v5_legacy_bridge/outbox.py` | +47 −0 | `a3d7d7a4…4413` | bot |
| `src/services/v5_legacy_bridge/outbox_flush_worker.py` | +33 −0 | `b173ea7c…6e9e` | bot |
| `src/services/v5_legacy_bridge/outbox_reconcile.py` | nový, nezapojený | — | nikde |

Nové testy: `test_readiness_paper_only.py`, `test_outbox_terminal_backlog.py`,
`test_outbox_reconcile_plan.py`.

## Doporučené pořadí review a nasazení (nic není nasazeno)

1. **Nezávislé review** přesného diffu (Codex):
   `docs/codex_prompts/CODEX_REVIEW_POST_C1_REMEDIATION_2026-11-18.md`.
2. **Dashboard (readiness):** jen `readiness_monitor.py` a `dashboard_web.py`, restart
   `cryptomaster-dashboard` (bota ne). `deploy_bot_files.sh` je jen pro bota a dashboard
   nepokrývá, takže potřebuje vlastní krátký postup s reviewem: záloha → `install` se SHA →
   `systemctl restart cryptomaster-dashboard` → `curl /api/dashboard/readiness` (`paper_only`)
   a `/api/dashboard/metrics` (200) → 10 min bez `[METRICS_COLLECTION_ERROR]`.
   **Rollback:** obnovit oba soubory ze zálohy (SHA výše) a restartovat dashboard.
3. **Bot (outbox viditelnost):** `outbox.py` a `outbox_flush_worker.py` nejsou v allowlistu
   `deploy_bot_files.sh`. Je potřeba reviewované rozšíření allowlistu a restart bota (nová fáze
   plánovače už po opravě svíček nevadí; zapsat marker). Nízká priorita: jde jen o viditelnost
   historického backlogu, který se nemění.
   **Rollback:** skript ho dělá automaticky při chybě, později obnovit ze zálohy skriptu.
4. **Rekonciliace:** až po rozhodnutí operátora (bod 3 blockeru).

## Co zůstává neověřené

Počet fetchů na symbol a minutu na serveru; chování opravy svíček za celý den a při výpadku
upstreamu; skutečný stav dokumentů v cloudu; růst disku za delší okno; pád hostu. Nic z toho
není důkaz edge, ziskovosti ani funkčního učení. C1 = `CONTRARIAN_NOT_SHOWN`.
