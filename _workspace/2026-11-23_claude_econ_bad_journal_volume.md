# Omezení záplavy `REJECT_ECON_BAD_ENTRY` v journalu — lokální implementace (Claude, 2026-11-23)

Zadání: `docs/codex_prompts/CLAUDE_ECON_BAD_JOURNAL_VOLUME_2026-11-23.md`. Jen lokální práce: bez SSH,
nasazení, restartu, Firebase a commitu. Žádný obchodní verdikt ani parametr se nemění. Důkazy jsou
v `_workspace/econ_bad_journal_20261123/`.

## Kolo 3 — nález R2 z re-review (`_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r1.md`)

**R2 potvrzen:** produkční `logging.basicConfig(stream=sys.stderr)` používá `StreamHandler`, který chybu
zápisu do streamu spolkne (`handleError`). Návrat z `log.warning()` proto nedokazuje zápis a potvrzení
z kola 2 mohlo smazat neodeslaný souhrn. Spolehlivé potvrzení zápisu z Pythonu možné není: handler
chybu skryje a journald může řádky zahodit i vlastním rate limitem.

**Změněný kontrakt (bez potvrzování):** čekající agregát, tokeny a `ack()` jsou pryč. Každý souhrn nese:
- `seq` (pořadové číslo od startu procesu);
- počty okna (`window_rejects`, `window_suppressed`);
- **kumulativní součty od startu procesu** (`total_rejects`, `total_suppressed`, `since_s`,
  `by_category_total`) se stejným stropem 16 kategorií + `other`.

Ztracená řádka se pozná podle mezery v `seq` a její počty jsou obsažené v součtech další doručené
řádky. Rozdíl součtů dvou po sobě jdoucích řádek se rovná počtům okna, takže řádky lze vzájemně
kontrolovat. Restart procesu začne znovu na `seq=1` (pozná se podle nového PID a `since_s`). Mez:
pokud se ztratí i poslední řádka před koncem procesu, její počty v journalu chybí. Mezera v `seq`
to neodhalí, protože žádná další řádka nepřijde.

**Testy (nové nebo upravené):**
- **skutečný `logging.Logger` + `StreamHandler` s chybujícím streamem** (`raiseExceptions=False`, přesně
  Codexova reprodukce): po obnovení streamu dorazí `seq=2` s `total_rejects=4 total_suppressed=2`,
  které obsahují ztracené okno;
- logger vyhazující výjimku: `seq=2`, `total_rejects=6 total_suppressed=4`, `window_rejects=3`;
- 10 chyb za sebou, každé okno jiných 25 kategorií: součty mají nejvýš 17 položek a souhrn `seq=11` má
  přesný celkový počet;
- rozdíly součtů odpovídají počtům oken (`[4, 6, 13]` oproti `[4, 2, 7]`).

Codexův reproduktor `_workspace/econ_bad_r1_independent_repro_20261123.py` volá odstraněné
`pending_snapshot()`, takže na novém kódu skončí `AttributeError`. Jeho scénář `StreamHandler` pokrývá
`test_streamhandler_swallowing_write_errors_loses_no_counts`.

**Ověření:**
- Celkem **30 PASS** (28 + 2 existující případy).
- Mutace **14/14 zachyceno**. Mutace potvrzování z kola 2 jsou nahrazené: součty se neakumulují, `seq`
  se nezvyšuje, chybí strop součtů, souhrn hlásí okno jako součet.
- `PROTECTED_SAME`.
- Nový postimage: SHA-256 `95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03`, 4075 řádků.
  Diff `rde.diff`: 4 hunky, +186/−48.

## Kolo 2 — oprava nálezu R1 z review (nahrazeno kolem 3) (`_workspace/2026-11-23_codex_review_econ_bad_log_limit.md`)

**R1 potvrzen:** limiter vynuloval počty starého okna ještě před zápisem souhrnu. Jedna chyba loggeru
je tak nenávratně ztratila.

**Oprava:**
- Uzavřené okno se sloučí do omezeného **čekajícího agregátu** (`_pending`) a `observe()` vrací
  `(emit, summary, token)`.
- `_econ_bad_should_emit_reject_detail()` volá `ack(token)` **až po úspěšném** `log.warning(summary)`.
  Při chybě agregát zůstává a další souhrn ho zahrne. Souhrn nese `windows=N` (počet pokrytých oken)
  a součet `window_s`.
- Opakované chyby slučují okna do téhož agregátu se stejným stropem kategorií (16 + `other`), takže
  paměť je omezená.
- `ack()` se starým tokenem nic nesmaže. Novější souhrn obsahuje i starší nepotvrzená okna.
- Zbývající mez: kdyby starší zápis uspěl až po vzniku novějšího souhrnu, což vyžaduje zápis delší
  než okno, mohla by se okna v logu objevit dvakrát. Počty se tím neztratí.

**Nové testy:**
- jednorázová chyba a pak úspěch: přesně `windows=2 rejects=6 suppressed_details=4`, agregát se smaže
  až po úspěchu a další okno se nezapočte dvakrát;
- 10 chyb za sebou s 25 kategoriemi v každém okně (pokaždé jiné): agregát nejvýš 17 položek a souhrn
  po obnově má přesný celkový počet;
- při trvale rozbitém loggeru jsou volání `track_blocked`, near-miss, flush a emit beze změny;
- starý token nesmaže novější počty.

**Ověření:**
- Celkem **29 PASS** (27 + 2 existující případy).
- Mutace **14/14 zachyceno**. Nové: potvrzení i při selhaném zápisu, přepsání místo sloučení,
  potvrzení bez kontroly tokenu, chybějící strop při slučování.
- `PROTECTED_SAME`, AST Python 3.12: PASS.
- Nový postimage: SHA-256 `07e3b7bf209baa0fd738511283db869e13f0d5db2d3e510c692f020a340b2a5e`
  (LF `c0de5142…3a05`), 4086 řádků. Diff `rde.diff`: 4 hunky, +197/−48.

## Výsledek

Za příznakem `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED` (**výchozí vypnuto**) se při ECON BAD odmítnutí
omezí jen dva detailní výpisy: `[ECON_BAD_ENTRY_RETURN_TRACE]` a `print("decision=REJECT_ECON_BAD_ENTRY …")`.
V každém okně 60 s se první odmítnutí každé kategorie vypíše celé, další se jen počítají. První odmítnutí
po konci okna zapíše jednu řádku `[ECON_BAD_REJECT_LOG_SUMMARY]` s počty okna a kumulativními součty od
startu procesu (formát z kola 3):

```
[ECON_BAD_REJECT_LOG_SUMMARY] seq=1 window_s=60 window_rejects=11 window_suppressed=9 total_rejects=11 total_suppressed=9 since_s=60 by_category_total(rejects/suppressed)=weak_ev=8/7,weak_p=3/2
```

Kategorie je úvodní token `[a-z_]` důvodu (`"weak_ev (ev=0.03<0.045)"` → `weak_ev`), nejvýš 40 znaků a
nejvýš 16 kategorií; zbytek padá do `other`. Volný text tedy stav nezvětší. Stav je chráněný zámkem.
Při jakékoli vnitřní chybě omezovač vrátí „vypsat“, tedy dosavadní chování; chyba loggeru u souhrnu
se spolkne. Nejsou v tom žádné identifikátory rozhodnutí ani zápisy do Firebase.

Známá mez: souhrn se zapíše až při prvním odmítnutí po konci okna. Když odmítnutí ustanou, počty
posledního okna se vypíšou až s dalším odmítnutím.

## Co se v rozhodování nezměnilo (VERIFIED testy)

- Větev v `evaluate_signal` dál vrací `None`. Její vedlejší efekty se **beze změny pořadí** přesunuly
  do `_econ_bad_reject_outputs()`, aby šly testovat:
  1. `_update_econ_bad_near_miss`
  2. rozhodnutí o výpisu
  3. `_trace_econ_bad_entry_return` (dál volá i interní resolver)
  4. `track_blocked("ECON_BAD_ENTRY")`
  5. `print` (jediný podmíněný krok)
  6. `_maybe_flush_econ_bad_diagnostics`
  7. `_maybe_emit_econ_bad_diag_from_reject`
- `track_blocked`, near-miss, flush a emit běží při každém odmítnutí. Test porovnává stejnou sekvenci
  30 odmítnutí s pěti různými důvody při vypnutém a zapnutém příznaku a vyžaduje **identické** záznamy.
- `[ECON_BAD_READY_BUT_REJECTED]` (invariant) se vypíše při každém výskytu i tehdy, když je detail
  potlačený. Trace pro `TAKE`/recovery probe a jiné důvody odmítnutí se neomezují.
- Neměnily se prahy, P0, risk, sizing, TP/SL, executor, Stonkfly, učicí politika ani periodické
  ECON BAD souhrny.

## Preimage / postimage a diff

| | SHA-256 (bajty) | SHA-256 (LF) | řádky |
|---|---|---|---|
| preimage (pracovní strom) | `4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae` | `15e59d9f…cae8` | 3937 (CRLF) |
| postimage (pracovní strom) | `9ea893265888e06335bb44bb7195e1eeacc1688027506ec71ec307df77bce698` | `8443d2da…e6a9` | 4046 (CRLF) |

Diff `_workspace/econ_bad_journal_20261123/rde.diff`: 4 hunky, +157/−48. Z toho 29 řádků trace je jen
odsazení pod `if emit_detail:` a 19 řádků větve je přesunutých do helperu; zbytek je sekce omezovače.
Kopie preimage je v `realtime_decision_engine.before.py`.

**Shoda se serverem: NOT_VERIFIED.** Lokální soubor je bajtově totožný s kopií
`_workspace/learning-cadence-20261022-before/` (22. 10.). Kopie `server_code_20260921` i
`before_entry_consolidation_20260921` se liší (4312 řádků). Pracovní strom má proti HEAD +1/−376
cizích změn, takže HEAD také není produkční základ. Před nasazením je potřeba živá kopie (viz níže).

## Testy a mutace

- `tests/test_econ_bad_reject_log_limit.py` (23 testů) + dva existující případy z
  `tests/test_v10_13u_patches.py` (`…entry_return_trace_emits_on_weak_ev_reject`,
  `…ready_but_rejected_invariant_emits`): **25 PASS**.
- Pokrývá:
  - vypnutý příznak a neplatné hodnoty (8 variant): každý detail se vypíše;
  - zapnutý příznak (5 variant): 1 detail z 50, ale 50× `track_blocked`, near-miss, flush a emit;
  - shodu side effectů vypnuto/zapnuto;
  - hranici okna (59,9 s bez souhrnu, 60,1 s s přesným souhrnem a resetem);
  - okamžitý výpis nové kategorie a omezenou kardinalitu;
  - deterministický test zámku a souběh 8 vláken × 3000 volání s přesnými počty;
  - invariant viditelný při potlačení, neomezený `TAKE` trace;
  - chybu omezovače i loggeru;
  - statickou kontrolu delegace a pořadí ve větvi.
- Bez opravy testy selžou: modul nemá `ECON_BAD_REJECT_LOG_LIMIT_FLAG` ani helper.
- Mutace (`mutations.py`, izolovaná kopie): **10/10 zachyceno** (`mutation_results.json`):
  - obě povinné: vrácený výpis při každém odmítnutí (print i trace) a vynechaný `track_blocked`;
  - dále: příznak ve výchozím stavu zapnutý, podmíněný near-miss, bez stropu kategorií, chyba
    v počítání potlačených, bez zámku, invariant podmíněný detailem a chyba, která by detail skryla.
- Syntaxe pro Python 3.12: PASS.
- **Ochrana runtime dat:** `protected_sha.py` před i po všech bězích PROTECTED_SAME (šest souborů +
  obsah `runtime/`, `src/runtime/`).
- **Vedlejší nález:** import `realtime_decision_engine` (přes `firebase_client`) v čisté kopii stromu
  vytvoří `runtime/firebase_cache.sqlite`. Guard v conftestu to správně shodí, proto má mutační skript
  zahřívací běh. Jde o starší vedlejší efekt importu, ne o tuto změnu. V hlavním stromu soubor existuje
  a jeho hash se nezměnil.

## Objem journalu: měření NOT_VERIFIED

Údaj ~48 tis. řádků za ~16 min pochází z mého dřívějšího `grep -oE "REJECT_[A-Z_]+"`. Ten počítal
řádky s alespoň jedním `REJECT_…` tokenem, ne rozhodnutí. Každé ECON BAD odmítnutí vypisuje nejméně
dvě takové řádky (trace s `final_decision=REJECT_ECON_BAD_ENTRY` a `print`). Řádově jde tedy spíš
o ~24 tis. odmítnutí, ale bez rozpadu podle markerů je to **NOT_VERIFIED**. O kolik se historie
journalu prodlouží, neslibuji. Lokální kopie journalu není k dispozici.

Reprodukovatelný read-only postup (na serveru, před a po aktivaci, stejné 10min okno):

```sh
J="journalctl -u cryptomaster --since -10min --no-pager"
journalctl -u cryptomaster --no-pager -o short-iso | head -1          # skutečné pokrytí journalu
$J | wc -l                                                           # řádky / 10 min
$J | grep -c "\[ECON_BAD_ENTRY_RETURN_TRACE\]"
$J | grep -c "decision=REJECT_ECON_BAD_ENTRY"
$J | grep -c "\[ECON_BAD_REJECT_LOG_SUMMARY\]"
$J | grep -c "on_price("
$J | grep -oE "\[[A-Z0-9_]{4,}\]" | sort | uniq -c | sort -rn | head -20   # dominantní markery
```

Pokud po aktivaci pokrytí nevzroste, dalším krokem je najít další dominantní marker z posledního
příkazu. Nepotlačovat nic dalšího bez samostatného důkazu.

## Návrh nasazení (oddělený, NENASAZENO)

1. Read-only stáhnout živý `/opt/cryptomaster/src/services/realtime_decision_engine.py` a zapsat jeho
   SHA-256 (preimage).
2. Artefakt = **serverové bajty + přesně tento diff**, sestavený jako u předchozích nasazení
   (`_workspace/deploy_post_c1_20261119/eol_preserve.py`): nezměněné řádky bajtově identické, kontrola
   hunků proti `rde.diff`. Pokud se serverová verze od lokální liší a diff nejde čistě aplikovat,
   zastavit a připravit nový diff.
3. Nástroj: přidat `src/services/realtime_decision_engine.py` do `ALLOWED_FILES` a
   `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED` do `ALLOWED_KEYS`. V `deploy_env_check.py` přidat klíč do
   striktních bool klíčů (`true`/`false`), protože kód tiše bere neznámé hodnoty jako vypnuto. Vlastní
   review.
4. Příkaz: `LABEL=econ-bad-log-limit`, `FILES` = jen RDE, `VARS="RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true"`,
   `EXPECTED_SHA256` = artefakt, `EXPECTED_PREIMAGE_SHA256` = živý soubor, `DROPIN_NAME` řazený za
   `zzzzzzzzzzzzz-explore-bucket-cap.conf`. Skript ověří PAPER/REAL a hodnotu v prostředí nového MainPID.
5. Účinek ověřit postupem měření výše. V journalu se musí objevit `[ECON_BAD_REJECT_LOG_SUMMARY]`
   a počet `[ECON_BAD_ENTRY_RETURN_TRACE]` řádků klesnout.
6. Rollback: smazat drop-in, nebo nastavit příznak na `false` (bez změny kódu), nebo obnovit preimage
   ze zálohy skriptu.
7. Restart vytvoří marker kohorty. Jde o změnu observability, ne o novou strategii; obchody před ním
   a po něm se neslučují.

Před změnou služby je potřeba nezávislé review kódu i nasazovacího kroku.
