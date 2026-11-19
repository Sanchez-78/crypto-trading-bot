# Incident lokální cache.sqlite a oprava izolace testů (Claude, 2026-11-18)

Zadání: `docs/codex_prompts/CLAUDE_REPAIR_POST_C1_TEST_ISOLATION_2026-11-18.md`. Jen lokální práce:
bez serveru, deploye, restartu a commitu. Runtime DB nebyla obnovována, resetována ani zapisována.
Důkazy jsou v `_workspace/cache_isolation_repair_20261118/`.

## Časová osa a síla důkazů

| Čas (UTC) | Událost | Důkaz |
|---|---|---|
| do 07:54 | `local_learning_storage/cache.sqlite` SHA `31767b56…7646` | stabilní ve všech mých bězích přes izolovaný runner (9.–18. 11.) |
| ~07:54:58 | Codex spustil sedm review souborů **přímo z kořene**; SHA se změnil na `0f2fbd24…0d7e` (mtime 07:54:58) | review `_workspace/2026-11-18_codex_review_post_c1_remediation.md` |
| 08:08 | stav: 172 032 B, `quick_check ok`, `schema_version` 29, 473 `closed_trades`, 40 sloupců | `a1_current_state.txt`, `a1_readonly_inspection.txt` (`mode=ro` + `query_only`) |

**Spolupříčina na mé straně:** do zadání review jsem zařadil `tests/test_dashboard_contract_fixes.py` a
neupozornil, že ho lze bezpečně spouštět jen přes izolovaný runner. Já sám jsem ho pouštěl jen přes
runner, proto se problém neprojevil dřív.

## Obsahový rozdíl DB: NOT_VERIFIED

- Kopie s původním SHA neexistuje. DB není v gitu (`git ls-files` prázdné) a v projektu ani v
  `CryptoMaster_v5_validation_checkout` jsem jinou kopii nenašel (`a1_copies_search.txt`).
- **Nepřímé indicie** (nejsou to důkazy): nejnovější `closed_trades.created_at` je z
  2026-10-02 a stav auditora ze září, takže dnes nepřibyl žádný řádek s aktuálním časem. Žádný test v
  sadě nezapisuje přes `lpc` mimo přesměrovanou fixture (`cache_db`, explicitní `monkeypatch`).
- **Mechanismus** jsem ověřil synteticky (`repro_import_side_effect.py`/`.json`, skutečná DB před i
  po beze změny):
  - import `local_persistent_cache` nad **aktuálním** schématem hash **nemění** (`c3624a98…` = `c3624a98…`);
  - import nad DB bez dvou nejnovějších sloupců hash **mění**: `_init_db()` je přidá přes
    `ALTER TABLE … ADD COLUMN`, řádky zůstanou a `schema_version` vzroste o 2.
- Sloupce `predicted_gross_move_bps` a `predicted_net_edge_bps` jsou jen v necommitnutém pracovním
  stromu, ne v gitu. **Nejpravděpodobnější vysvětlení:** lokální DB je neměla a první import z kořene
  je doplnil. Řádky by tím zůstaly zachované. Souběžný jiný proces vyloučit nelze.
- **Dopad:** jde o lokální vývojovou kopii, ne o produkční DB na serveru.

## Úkol A — oprava příčiny a regrese

**Příčina:** `tests/test_dashboard_contract_fixes.py:22` importuje `local_persistent_cache` při
collection. Modul má relativní `LOCAL_DB_PATH` (`local_persistent_cache.py:33`) a při importu volá
`_init_db()` (`:189`), který otevírá DB pro zápis a migruje schéma. Fixture přesměruje cestu až
později (`:121-126`). Stejný vzor mají i jiné testy, které modul importují na úrovni modulu.

**Oprava (jen `tests/conftest.py`, produkční kód beze změny):**
1. **Prevence před collection:** conftest se načítá dřív než testové moduly. Naimportuje
   `local_persistent_cache` jednou s `cwd` v soukromém dočasném adresáři (`_init_db()` tedy zapíše
   jen tam) a přesměruje `LOCAL_CACHE_DIR`, `LOCAL_DB_PATH` a `LOCAL_STATE_DIR` na absolutní dočasné
   cesty. Další importy dostanou tento objekt modulu a runtime cestu nikdy neinicializují. Úklid
   zajistí `atexit`. Žádný test nespoléhá na výchozí relativní hodnotu (ověřeno grepem).
2. **Detekce:** `pytest_sessionfinish` porovná SHA skutečné `local_learning_storage/cache.sqlite` se
   stavem při načtení conftestu. Při změně vypíše `RUNTIME DB CHANGED DURING TESTS` a nastaví
   `exitstatus` na selhání, takže případný zbylý zápis (např. reload modulu) nepřejde potichu.

**Regrese `tests/test_conftest_runtime_db_isolation.py`** (3 testy): vnořený pytest se spouští z
kořene izolované kopie v `tmp_path` se **syntetickou starší DB** a modulem, který cache importuje na
úrovni modulu (jako test kontraktu). Skutečnou DB hlídá fixture.
- opravený conftest: syntetická DB beze změny, běh projde;
- **stará podoba** conftestu: syntetická DB se změní a přibudou sloupce. Kontrola tím dokazuje, že
  nebezpečí je reálné a test by návrat vady zachytil;
- prevence vypnutá, detekce ponechaná: běh selže s `RUNTIME DB CHANGED DURING TESTS`.

**Upozornění:** lokální DB už má nové schéma, takže by se dnes nezměnila ani se starou podobou testu.
Čistý přímý běh proto sám o sobě opravu nedokazuje; důkazem je regrese se syntetickou starší DB.

## Úkol B — plánovač rekonciliace (odděleno od incidentu)

**Nález (Codex) potvrzen:** `LegacyPaperCloseEvent.to_dict()` (`event_models.py:73-94`) zapisuje
`event_type="paper_close"` a pole `exit_ts`/`exit_price`, žádné `status`. Plánovač proto mohl
existující close přepsat. Navíc `learning_update` se merguje do téhož dokumentu a jeho payload z
`apply_learning_from_close` může `event_type` přepsat.

**Oprava `src/services/v5_legacy_bridge/outbox_reconcile.py`** (stále `ENABLED=False`, bez I/O a
bez executoru):
- nová `doc_state()`: `absent`, `closed` (`event_type=="paper_close"` **nebo** přítomné obě
  `exit_ts`+`exit_price`), `open` (`event_type=="paper_open"` a žádné exit pole) a jinak `unknown`;
- `unknown` vede vždy na `UNKNOWN`, nikdy na přepis. Existující close → `SKIP_PRESENT`;
- `learning_update` se merguje jen do uzavřeného dokumentu nebo do dokumentu, jehož close je v tomtéž
  plánu skutečně naplánovaný v rámci stropu. Jinak `DEFERRED_CLOSE_MISSING` nebo `DEFERRED_NO_TRADE_DOC`;
- každá akce nese `expect` (pozorovaný stav) pro compare-before-write budoucího executoru. Docstring
  výslovně říká, že snímek sám zápis neopravňuje.

Testy `tests/test_outbox_reconcile_plan.py` (10) používají **skutečné** dokumenty z `to_dict()`:
uzavřený dokument po learning merge, vymyšlené `status`, rozporný dokument, open/close/learning a strop.

**Navíc z review:** `OutboxFlushWorker.get_status()` předává `backlog_error`, takže chyba DB už se
netváří jako nulový backlog (test v `test_outbox_terminal_backlog.py`).

**Opravena nestabilita testu:** `test_same_key_across_open_and_close_is_not_a_duplicate` porovnával
celý slovník včetně `oldest_terminal_age_s`, které roste s časem, a občas selhal. To nejspíš vysvětluje
dříve nevysvětlené jedno selhání v mutačním harnessu (report 2026-11-18 post-C1). Teď porovnává jen počty.

## Testy, mutace a hashe

- Přímo z kořene, všech sedm review souborů + regrese, v pořadí dopředu i obráceně:
  **140 PASS, 9 SKIP** (finální) a 137 PASS (před úkolem B). SHA **6/6 chráněných souborů beze změny**
  (`sha_before_direct.txt` = `sha_after_all.txt`).
  - Před přímým během jsem uložil read-only kopii lokální DB `cache.sqlite.pre_direct_run`
    (`0f2fbd24…`), aby bylo s čím porovnat.
- Regrese v izolovaném runneru: 3 PASS.
- Mutace (`mutation_results.json`, izolovaná kopie bez runtime DB): **6/6 zachyceno**, každá jen
  svým cíleným testem. Mutace: uzavřeno jen podle `event_type`, podle vymyšleného `status`,
  nerozpoznaný dokument jako absent, merge do otevřeného dokumentu, open přes existující dokument a
  skrytý `backlog_error`. Mutace conftestu pokrývá sama regrese (stará podoba a obejitá prevence).
- Stabilita: 3× 16 PASS po sobě. AST Python 3.12: PASS.

## Diff (necommitnuto, k nezávislému review)

| Soubor | Změna |
|---|---|
| `tests/conftest.py` | prevence + detekce zápisu do runtime DB (úkol A) |
| `tests/test_conftest_runtime_db_isolation.py` | nový regresní test (úkol A) |
| `src/services/v5_legacy_bridge/outbox_reconcile.py` | `doc_state`, `expect`, pravidla learning (úkol B) |
| `tests/test_outbox_reconcile_plan.py` | testy podle skutečného kontraktu (úkol B) |
| `src/services/v5_legacy_bridge/outbox_flush_worker.py` | `backlog_error` v `get_status()` |
| `tests/test_outbox_terminal_backlog.py` | test `backlog_error` + oprava nestabilní kontroly |

## Kolo 2 — oprava nálezů nezávislého review plánovače (P2 ×2)

Review (`_workspace/2026-11-18_codex_review_post_c1_remediation.md`, reprodukce v
`post_c1_remediation_review_20261118/independent_final.json`) schválilo readiness a viditelnost
outboxu (kód) a vrátilo plánovač. Obě reprodukce jsem potvrdil a opravil (`ENABLED=False` zůstává):

1. **Neúplný, rozporný nebo cizí dokument už není uzavřený.** `doc_state(doc, key)` nově vyžaduje
   `trade_id == key` (chybějící identita vede na `unknown`). Za `closed` se počítá jen úplný close
   dokument: `symbol`, `side` a konečná čísla `exit_ts`/`exit_price` (ne `None`, NaN ani bool) a
   `event_type` jiný než `paper_open`. Za `open` jen `paper_open` s konečnými `entry_ts`/`entry_price` a
   bez jakéhokoli exit pole. Všechny čtyři reprodukce z review (`{"event_type":"paper_close"}`, null exit
   pole, open s null exit a cizí `trade_id`) teď vedou na `UNKNOWN` bez zápisu.
2. **Learning po plánovaném uzavření.** Platí pro `absent` i `open`: když se close téhož klíče vejde do
   stropu, learning dostane `MERGE_LEARNING` s `expect="closed"` a `depends_on="paper_close:<key>"`.
   Bez rozpočtu na close zůstane odložený a bez závislosti. Docstring popisuje kontrakt pro budoucí
   executor: akce v pořadí plánu, `expect` je stav v čase zápisu, re-read před zápisem a přeskočení
   akce, jejíž závislost neuspěla.

Testy `test_outbox_reconcile_plan.py`: 27 (parametrizované reprodukce, absent/open → close → learning se
stropem 2, 1 i 0). Mutace: **10/10 zachyceno** (identita, hodnota vs. přítomnost exit polí, holé
`event_type`, symbol/side, nerozpoznaný dokument jako absent, odložený learning po close, merge do
otevřeného dokumentu, závislost u odloženého, open přes existující dokument a `backlog_error`).
Přímo z kořene všech 8 souborů: **157 PASS, 9 SKIP**. SHA 6/6 chráněných souborů beze změny
(`sha_after_round2.txt`). AST Python 3.12: PASS.

## Kolo 3 — re-review (CHANGES_REQUIRED) a nový incident chráněných souborů (2026-11-19)

**Oprava nálezu re-review** (`_workspace/2026-11-18_codex_rereview_outbox_reconcile.md`, P2):
`doc_state()` nyní pro `open` i `closed` vyžaduje `symbol` jako neprázdný řetězec, `side` ∈ {`BUY`,
`SELL`} a čas i cenu jako konečná **kladná** čísla. Za `closed` uzná jen `event_type == "paper_close"`.
Ověřil jsem, že `build_learning_update()` (`learning_bridge.py:157-180`) vlastní `event_type` nevkládá,
takže výjimka pro jiné typy byla nepodložená a je zrušená; nedoložený tvar vede jen ke zbytečnému
odkladu. Docstring uvádí blokátor aktivace: re-read + `set()` není atomické, executor potřebuje
transakci nebo precondition. Testy: 42 v `test_outbox_reconcile_plan.py` (včetně všech reprodukcí
re-review). Mutace **14/14 zachyceno** (navíc: libovolný ne-open typ jako close, chybějící kontrola
symbolu, `side` jen pravdivostně, povolená nula nebo záporná hodnota).

**Incident (zjištěn úvodní kontrolou kola 3):** `server_local_backups/paper_adaptive_learning_state.json`
(→ `27fd24dc…`) a `server_local_backups/learning_state_phase1.json` (→ `49b740bd…`) se změnily
**2026-11-19 07:06:26 UTC** (vnitřní `timestamp` `2026-11-19T07:06:26.757015`).
- **Původce (silná nepřímá evidence, ne důkaz):** souběžná ranní autonomní session ve stejném
  pracovním stromu (`_workspace/autonomy/daily.md`, záznam 19. 11. 07:02, práce na
  `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET`). V 07:03–07:06 upravila `paper_trade_executor.py` a další
  soubory, spouštěla pytest z kořene bez `-B` (vznikly `.pyc` `paper_adaptive_learning`, `bot2/main`,
  `test_paper_mode`, `test_p1_paper_exploration` …), v 07:06:26 se změnily oba soubory a v 07:06:27
  vzniklo `src/runtime/v5_trade_outbox.sqlite`. Jiný Python proces na stroji neběžel.
- **Moje práce původcem není:** úvodní kontrola (stdin varianta, správný návratový kód) změnu našla
  ještě před mým pytestem. Hashe před a po mém běhu jsou totožné (`sha_pre_round3_mut.txt` =
  `sha_post_round3_mut.txt`). Izolovaná reprodukce `repro_backup_write.py(.json)` všech osmi souborů
  jednotlivě i dohromady v obou pořadích kopie souborů nezměnila (skutečné soubory beze změny).
- Konkrétní test, který zapsal, je NOT_VERIFIED. Soubory jsem neobnovoval ani neupravoval.

**Chyba v mé kontrole hashů:** `rtk diff a b` (dva soubory) vrací **0 i při rozdílu**; správně se
chová jen stdin varianta. Hlášení `PROTECTED_SAME_6_OF_6` na konci kola 3 bylo proto **neplatné**.
Výsledky kol 1 a 2 jsem přepočítal v Pythonu a platí (`sha_after_direct`, `sha_after_all`,
`sha_after_round2` = `sha_before_direct`). Porovnání dál dělám jen v Pythonu.

**Doporučení:** autonomní session musí spouštět testy přes izolovaný runner a hashe porovnávat jinak
než přes `rtk diff`. Rozšíření detekce provedeno v kole 4 (na pokyn uživatele).

## Kolo 4 — detekce na všech šesti chráněných souborech (2026-11-19)

`tests/conftest.py`: při načtení se uloží SHA-256 šesti chráněných souborů z `AGENTS.md` a otisk
(velikost + `mtime_ns`) každého souboru pod `runtime/` a `src/runtime/`. `pytest_sessionfinish`
porovná stav s koncem běhu. Změna, vznik nebo zmizení souboru vypíše
`PROTECTED RUNTIME FILES CHANGED DURING TESTS` se seznamem cest a běh shodí. Prevence pro
`local_persistent_cache` je beze změny.

Regrese `tests/test_conftest_runtime_db_isolation.py` (8 testů, vnořený pytest v `tmp_path`):
- zápis do `server_local_backups/learning_state_phase1.json` (tvar incidentu 19. 11.) i do
  `data/paper_open_positions.json` běh shodí;
- nový soubor v `src/runtime/` i v `runtime/` běh shodí;
- zápis mimo chráněné cesty běh nechá projít;
- dosavadní tři testy (prevence, stará podoba, obejitá prevence) zůstávají.

Mutace conftestu (`mutations_conftest.py`, izolovaná kopie): **4/4 zachyceno** (jen `cache.sqlite`,
bez skenu runtime adresářů, nenastavený `exitstatus`, vypnutá prevence). Přímo z kořene všech 8
souborů v obou pořadích: **177 PASS, 9 SKIP**. Hashe porovnané v Pythonu (`protected_sha.py`,
výchozí stav = stav po ranní změně): **beze změny** včetně výpisu `runtime/` a `src/runtime/`.

Omezení: detekce zachytí změnu až na konci běhu (nezabrání jí) a jen u běhů, které tento conftest
načtou. Soubory mimo šestici a runtime adresáře (např. jiné `server_local_backups/*`) nehlídá.

## Kolo 5 — review plánovače R3 a hlídání v conftestu (oba CHANGES_REQUIRED, 2026-11-19)

Review: `_workspace/2026-11-19_codex_review_planner_r3_conftest_guard.md`.

**Oprava počtu z kola 3:** mutací plánovače bylo **13**, ne 14, jak jsem uvedl (`mutation_results.json`
je správně, chyba byla v reportu).

**A1 (zkrácený close jako úplný) — opraveno.** `doc_state()` nově ověřuje **každé pole, které writer vždy
zapisuje**, včetně typu (`_OPEN_FIELDS`, `_CLOSE_FIELDS` podle `event_models.py`):
- u close výsledek obchodu (`exit_reason`, `gross_pnl`, `fees`, `spread`, `net_pnl`, `net_pnl_pct`,
  `duration_seconds` ≥ 0, `learning_eligible`/`readiness_eligible` jako bool);
- u open `size` > 0, `expected_move_bps`, `required_move_bps`, `cost_edge_ok` jako bool, volitelné
  texty `strategy_id`/`regime`/`bucket`;
- u obou `real_orders_allowed is False`, `metadata` jako mapping, neprázdné `created_at` a `symbol`
  jen z velkých ASCII písmen a číslic, takže `" "` neprojde.

Ověřil jsem, že learning merge (`build_learning_update`, `build_close_metadata`) žádné z těchto polí
nepřepisuje jiným typem a `event_type` nepřidává. Sloučený close proto zůstává `closed`. Docstring
navíc uvádí, že executor musí porovnat i payload řádku s cloudovým dokumentem, protože plán porovnává jen stav.
Testy: 96 (Codexova reprodukce, vynechání každého povinného pole zvlášť u open i close, neplatné
hodnoty). Mutace plánovače: **17/17** (nově jen markery u close, ignorované schéma open, povolené
chybějící pole, libovolný text jako symbol, nekontrolované `real_orders_allowed`, záporná doba).

**B1 (stejná velikost a mtime) — opraveno.** `_protected_snapshot()` hashuje obsah **každého** souboru
pod `runtime/` a `src/runtime/` (dnes ~170 KiB). Do komentáře jsem doplnil limity: hlídá jen koncový
stav, soubor vzniklý a smazaný mezi snímky nezachytí, a souběžný proces nebo SQLite `-wal`/`-journal`
shodí běh jako „during tests“. Totéž umí i `protected_sha.py` (předtím jen výpis souborů).
Regrese (14 testů):
- přepis existujícího souboru stejné velikosti s obnoveným mtime (3 cesty);
- smazání existujícího souboru (runtime i chráněný JSON);
- test, že všech šest souborů ze sekce „Runtime data“ v `AGENTS.md` je v conftestu.

Mutace conftestu: **8/8** (nově hash nahrazený metadaty, ignorované smazání, vynechaný jeden ze šesti
souborů, dva různé).

Přímo z kořene všech 8 souborů v obou pořadích: **237 PASS, 9 SKIP**. Hashe přes `protected_sha.py`
(šest souborů a obsah všech souborů v runtime adresářích) **beze změny**. AST Python 3.12: PASS.

## Závěr review (2026-11-19)

Re-review `_workspace/2026-11-19_codex_rereview_planner_r4_conftest_guard_r2.md`: **A plánovač APPROVE
(kód)**, **B conftest APPROVE**. Schválení se netýká aktivace plánovače ani nasazení. Neblokující P3
(`OverflowError` u obřího `int` v `_number()`) jsem zapracoval: `_number()` výjimku zachytí a vrátí
`unknown`, test s `10**1000` ve dvou polích. Cílené tři soubory: 118 PASS, `protected_sha.py`: PROTECTED_SAME.

## Commit (2026-11-19)

Commitnuty jen schválené hunky (index sestaven bez stagování celých souborů):
- `readiness_monitor.py`, `dashboard_web.py` a `outbox.py`: patch z porovnání se serverovou kopií,
  aplikovaný na HEAD (`approved_hunks_3files.patch`).
- `outbox_flush_worker.py`: HEAD obsahuje starší verzi, než běží na serveru, takže se přesně 35
  schválených řádků vložilo na kotvy (`stage_flush_worker.py`).
- Ostatní rozdíly v `dashboard_web.py` (226/73 proti HEAD) a `outbox_flush_worker.py` (60/176) zůstávají
  necommitnuté v pracovním stromu.

Při ověření obsahu indexu (`git checkout-index` do dočasného adresáře) selhal regresní test conftestu.
Starší schéma vyráběl odebráním sloupců `predicted_*`, které existují jen v necommitnuté verzi
`local_persistent_cache.py`. Teď odebírá sloupec `side`, který migrace přidává v obou verzích.
Export indexu: 152 PASS (7 souborů; `tests/test_sec_01_dashboard_boundary.py` není v gitu). Pracovní
strom: 239 PASS, 9 SKIP. Mutace conftestu 8/8, `protected_sha.py`: PROTECTED_SAME. Do commitu nejde
kopie lokální DB `cache.sqlite.pre_direct_run`.

## Neuzavřená rizika

- Přesný obsahový rozdíl lokální DB před incidentem je NOT_VERIFIED. Kopii před incidentem nelze
  vytvořit dodatečně.
(Aktualizováno 2026-11-19 po závěrečném review.)

- Přesný obsahový rozdíl lokální `cache.sqlite` před incidentem 18. 11. je NOT_VERIFIED. Kopii před
  incidentem nelze vytvořit dodatečně. Změnu obou `server_local_backups/*.json` z 19. 11. 07:06 UTC
  jsem neobnovoval. Konkrétní test souběžné session, který ji způsobil, je NOT_VERIFIED.
- Prevence chrání import `local_persistent_cache` při collection. Test, který modul **reloaduje** nebo
  odstraní ze `sys.modules` a pak ho znovu importuje z kořene, by mohl znovu zapsat. Takový případ
  zachytí detekce (běh selže), nezabrání mu.
- Detekce v `tests/conftest.py` hlídá SHA všech šesti chráněných souborů a obsah všech souborů pod
  `runtime/` a `src/runtime/`. Hlídá ale jen koncový stav a jen běhy, které tento conftest načtou.
  Soubor vzniklý i smazaný během běhu nezachytí. Souběžný proces nebo zbylý SQLite `-wal`/`-journal`
  shodí běh jako „during tests“. Jiné soubory v `server_local_backups/` mimo šestici nehlídá.
- Souběžné autonomní session sdílejí pracovní strom. Testy mají běžet přes izolovaný runner a hashe se
  porovnávají v Pythonu, ne přes `rtk diff a b`.
- Readiness a viditelnost outboxu mají APPROVE jen pro kód, ne pro nasazení. Dashboard potřebuje review
  nasazovacího kroku a outbox rozšíření allowlistu.
- Plánovač rekonciliace má APPROVE pro kód, zůstává `ENABLED=False` a nezapojený. Aktivace vyžaduje
  executor s atomickým zápisem (transakce nebo precondition), porovnání payloadu, vlastní review a
  rozhodnutí operátora, zda cloudovou historii vůbec rekoncilovat.
