# Re-review nasazovacího kroku ECON BAD po D4/D5 — 2026-11-23

**Verdikt: CHANGES_REQUIRED pro runbook; artefakt a schválený limiter zůstávají beze změny.** Opravy D4 a D5 odpovídají kódu. Při celkovém průchodu post-checkem jsem našel další tři místa, kde by správný provoz mohl být vyhodnocen chybně nebo by kontrola naopak nic neprokázala. Na server jsem se nepřipojoval, nenasazoval ani necommitoval.

## Ověřené D4/D5 a rozsah změny

- `src/services/realtime_decision_engine.py:803–837` drží `total_rejects`, `total_suppressed`, `seq` a `since_s` od startu procesu. Při každém rolloveru uzavře jedno okno a přičte jeho počty. Nový vzorec `Δtotal_rejects / (Δsince_s / 60)` v runbooku `:129–136` proto vrací sazbu za skutečnou dobu mezi dvěma doručenými souhrny. Mezery v `seq` rozdíl kumulativních počtů nezkreslují; součet `window_rejects` je použitelný jen při souvislém `seq`. Při méně než dvou souhrnech je výsledek správně `NOT_VERIFIED`. Výchozí sazba je 17 444 / 10 = **1 744,4 za minutu**.
- Pevná konzervativní mez `17 × počet zasažených 60s oken` na každý detailní marker (`:123–128`) odpovídá limitu 16 kategorií plus `other` v `src/services/realtime_decision_engine.py:794–837`. Zahrnuje i poslední neuzavřené okno. Kategorie z doručených souhrnů již nejsou tvrdým kritériem. Hodnota 187 předpokládá, že desetiminutové wall-clock okno skutečně odpovídá přibližně 600 sekundám monotónního času; při skoku systémových hodin je třeba místo této zkratky ověřit skutečný počet oken.
- `git diff 748e43e^ 748e43e` mění jen `AGENTS.md`, zadání/report a dvě kritéria runbooku. SHA-256 artefaktu a obou nástrojů jsou stále `95e499e7…2c03`, `981c8870…7d29`, `927cc096…51c5`; nezávislý read-only checker vrátil `ARTIFACT_BYTES_OK` a `COMMIT_BLOBS_OK`. Nasazovací příkaz je beze změny. Aktuální stav serveru je `NOT_VERIFIED`.

## D6 — pevná výstupní cesta pod `/tmp` při spuštění jako root

Měřicí příkaz v runbooku `:106–120` spouští root a zapisuje `grep ... > /tmp/econ_summaries.txt` (`:117`). Tato pevná cesta se otevře přepisem; pokud již ukazuje na jiný soubor (např. symlink), může příkaz přepsat cizí data. Skutečnou ochranu symlinků na serveru jsem bez SSH neověřoval a na ni nelze při schvalování runbooku spoléhat. `T=$(mktemp)` je bezpečnější, ale souhrny z něj se znovu posílají do pevné cesty. **Oprava:** ponechat souhrny v unikátním souboru vytvořeném `mktemp`, případně je vytisknout a vyhodnotit přímo z `"$T"` před jeho odstraněním. U každé dočasné cesty uvést bezpečné odstranění a nenechat existující `/tmp/econ_summaries.txt` přepisovat. Ověřit návratový kód `journalctl` a neprázdný výstup ještě před interpretací nulových počtů.

## D7 — souhrny musí patřit jednomu běhu procesu; tvrzení „bez chyb“ musí respektovat retenci

`seq`, `since_s` i kumulativní počty se po restartu vrátí na začátek (`src/services/realtime_decision_engine.py:763–767,800–804`). Formule v `:129–136` je platná jen pro dvě řádky ze **stejného procesu**. Desetiminutový výpis s `-o cat` ale neobsahuje PID. Pokud mezi A a B nastane restart, může vyjít nesmyslná nebo zdánlivě přijatelná sazba a změna PID může zůstat nepovšimnutá. Před výpočtem porovnat `MainPID` s PID v markeru `APPLIED OK` a ověřit, že se během měření nezměnil; při restartu označit post-check `NOT_VERIFIED` a vyšetřit restart. Počty `seq`, `since_s` a total musí v jednom běhu růst konzistentně.

Runbook `:104,122` zároveň požaduje „PAPER a REAL vypnuté“ a „0 tracebacků“. První formulace je nejasná: požadovaný stav je `TRADING_MODE=paper_train`, `ENABLE_REAL_ORDERS=false`, `LIVE_TRADING_CONFIRMED=false` a `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true` (viz `deploy/research_eval/deploy_env_check.py:73–79`). Po 15 minutách při doložené retenci journalu přibližně 15 minut nemusí být celý interval od restartu dostupný. „0 tracebacků“ lze tvrdit jen za skutečně pokrytý úsek journalu; chybějící část označit `NOT_VERIFIED`. Deploy skript první minutu kontroluje samostatně, další mezera ale může zůstat bez důkazu.

## D8 — malý a proměnlivý vzorek obchodních událostí není akceptační podmínka

Kritérium `:142–143` vyžaduje, aby `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` zůstaly „ve stejném řádu“. Výchozí desetiminutový vzorek má jen **3 a 4** události (`_workspace/econ_bad_deploy_20261123/baseline_journal_20261123.txt`). V dalším úseku může být legitimně 0 nebo 10 podle trhu a otevřených pozic; to by funkční nasazení falešně odmítlo. Stejný počet zase nedokazuje stejné rozhodování. Rovněž sazba odmítnutí v bodu 3 je závislá na trhu: porovnání s 1 744,4/min je užitečný kontext, nikoli samostatný důkaz správnosti. **Oprava:** oba počty a sazbu zaznamenat, ale nepoužívat jejich podobnost jako tvrdý PASS/FAIL. Ověřit průchod pipeline a absenci chyb; behaviorální invarianci dokládá připnutý, schválený diff a jeho testy. Pokud je provoz příliš řídký, účinek limitu označit `NOT_VERIFIED`, nikoli automaticky za neúspěch.

## Jednorázové doporučené znění kontrolních kritérií

Po zabezpečení dočasného výstupu lze body 1–5 nahradit tímto kontraktem:

> 1. `APPLIED OK`; služba je active, `MainPID` souhlasí s markerem nasazení a po dobu měření se nemění. Běžící prostředí má `TRADING_MODE=paper_train`, oba REAL příznaky `false` a příznak limiteru `true`. Journal prokazatelně dostupné části od restartu neobsahuje traceback; nedostupný čas je `NOT_VERIFIED`.
> 2. Pro dva souhrny A/B ze stejného procesu ověř `B.seq > A.seq`, `B.since_s > A.since_s`, `B.total_rejects ≥ A.total_rejects` a `B.total_suppressed ≥ A.total_suppressed`. Spočti `N=Δtotal_rejects`, `S=Δtotal_suppressed`, `R=N/(Δsince_s/60)`; ověř `0 ≤ S ≤ N` a `N−S ≤ 17 × Δseq`. Tato interní kontrola platí i při ztracených souhrnech. Má-li měření méně než dva souhrny nebo `N=0`, je provozní účinek `NOT_VERIFIED`; zjisti, zda bot stále generuje odmítnutí.
> 3. Za desetiminutové okno při stabilních hodinách nepřekročí každý detailní marker `17 × počet skutečně zasažených oken` (nejvýše 187); zaznamenej jeho počet, počet souhrnů, řádky a bajty celého journalu. Výchozích 17 444 detailů/marker a 1 744,4 odmítnutí/min použij jako kontext, nikoli pevný práh pro tržně proměnlivý provoz.
> 4. Mezery v `seq` eviduj jako ztrátu observability. Při >10 % chybějících hodnot mezi A a B prověř journald. Samotná mezera nespouští rollback; při restartu procesu se výsledky neslučují.
> 5. `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` vypiš jako provozní kontext, ne jako důkaz stejného rozhodování ani jako samostatnou podmínku úspěchu. Změřenou retenci uveď odděleně od odhadu.

Pokud se má `NOT_VERIFIED` po opakovaném měření změnit na operační rozhodnutí, runbook má výslovně určit, že je nutné prověřit zdroj odmítnutí a zdraví služby; neprohlásit nasazení za úspěšné jen na základě nízkého počtu detailů.

## Metoda a omezení

Kontrola byla statická; testy jsem u dokumentačního diffu znovu nespouštěl. Soubor výchozího měření obsahuje autorem zaznamenané agregáty, nikoli úplný export journalu; nezávisle ověřuji aritmetiku a konzistenci s kódem, ne serverové sčítání. Žádné SSH, nasazení, restart, commit, push ani zápis do runtime dat.
