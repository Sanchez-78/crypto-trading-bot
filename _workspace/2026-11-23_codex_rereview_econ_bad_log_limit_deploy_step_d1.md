# Re-review nasazovacího kroku ECON BAD po opravě D1 — 2026-11-23

**Verdikt: CHANGES_REQUIRED pro runbook, ne pro schválený kód ani artefakt.** D1 je opravený: nový základ měření a procenta sedí. Nová kritéria po nasazení ale používají kumulativní počítadlo jako desetiminutové a stanoví mez, kterou limiter negarantuje. Nasazení jsem neprováděl; server jsem nekontaktoval.

## Ověření opravy D1

- Soubor `_workspace/econ_bad_deploy_20261123/baseline_journal_20261123.txt` uvádí za 10 minut 153 824 řádek a 19 429 778 bajtů textu; z toho oba omezované markery dohromady 34 888 řádek a 7 815 303 bajtů. Přepočet: **22,6805 % řádek a 40,2233 % bajtů textu**. Deklarovaných 22,7 % a 40,2 % v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md:57–58` je správně. Při hypotetickém odstranění všech těchto zpráv a stálé rychlosti by 15 minut odpovídalo 19,4, respektive 25,1 minutám; skutečná retence je správně `NOT_VERIFIED` (`:64–66`). Čísla v podkladovém souboru jsou autorem zaznamenané agregáty, nikoli úplný export journalu; nezávisle tedy ověřuji aritmetiku, ne původní sčítání na serveru.
- Runbook odlišuje šest řádek jednoho odmítnutí od všech řádek journalu. Nové porovnání výslovně vyžaduje stejné desetiminutové okno a `journalctl -o cat` pro řádky i bajty (`:105–107`). To je s deklarovaným výchozím formátem srovnatelné. Pro přesnou reprodukci je vhodné zapsat i celý původní měřicí příkaz; agregát ho neobsahuje.
- `git diff c080775^ c080775` neobsahuje artefakt ani deploy nástroje. Místní SHA-256 jsou `95e499e7…2c03` (RDE artefakt), `981c8870…7d29` (deploy skript) a `927cc096…51c5` (kontrola prostředí), shodné s runbookem. Read-only kontrola `_workspace/econ_bad_deploy_independent_check_20261123.py` skončila `ARTIFACT_BYTES_OK` a `COMMIT_BLOBS_OK`. Aktuální bajty živého serveru jsou `NOT_VERIFIED`; nasazovací skript je má před zápisem ověřit. Záznam serverového importu je `AUTHOR_REPORTED`.

## Blokující nález D2 — `total_rejects` není počet za posledních deset minut

Runbook `:112–113` požaduje v souhrnech `total_rejects` „řádově ~17 tis. za 10 min“ po nejméně 15 minutách běhu (`:105`). `src/services/realtime_decision_engine.py:803,816–825` však toto pole počítá **kumulativně od startu procesu**, po uzavřených oknech. Po 15 minutách při stejné četnosti už může být přes 20 tisíc a dále roste, přestože limiter funguje správně. Desetiminutový počet je třeba vzít z rozdílu `total_rejects` na začátku a konci měřeného úseku (s vyznačením hranic oken), případně ze součtu `window_rejects` za okna v úseku. Samotné `total_rejects` se má hodnotit spolu s `since_s` jako kumulativní údaj, ne porovnávat s 17 444 přednasazovacími trace řádky.

## Blokující nález D3 — meze detailních výpisů a `seq` nejsou kontraktem limiteru

Runbook `:108–113` označuje kritéria za nezávislá na velikosti úspory, přesto vyžaduje „jednotky až desítky“ každého detailního markeru za deset minut. Limiter (`src/services/realtime_decision_engine.py:757–760,796,830–837`) ponechává první detail **každé** kategorie v **každém** 60sekundovém okně. Má až 16 pojmenovaných kategorií a `other`, tedy až 17 detailů na marker a okno. Desetiminutový interval může zasáhnout přibližně 11 oken: i přibližně 187 řádek na marker může být očekávaný, správný výsledek. Opravit kritérium na výrazný pokles oproti 17 444 při srovnatelné četnosti odmítnutí a kontrolu vůči skutečnému počtu kategorií/oken; pevný limit „desítky“ není opodstatněný.

Stejný bod požaduje `seq` „bez mezer“. Kontrakt v `src/services/realtime_decision_engine.py:763–767` výslovně připouští ztrátu souhrnné řádky v loggeru nebo journald: mezera v `seq` ji odhalí a další doručená řádka nese kumulativní součty. Požadovat rostoucí `seq` je správné; případnou mezeru je třeba zaznamenat jako ztrátu observability a součty rekonstruovat z kumulativních hodnot. Samotná mezera neprokazuje chybný limiter ani obchodní regresi. Pokud se má nasazení kvůli ztrátám logu zamítnout, runbook musí uvést samostatný měřitelný limit a reakci, ne implicitně považovat každou mezeru za chybu kódu.

## Rozsah a otevřené body

Změna D1 se týká dokumentace a evidence; testy jsem znovu nespouštěl. Schválený kód a dřívější cílené testy zůstávají v předchozím review. Nebylo SSH, nasazení, restart, commit, push ani zápis do runtime dat. Retence, skutečný účinek na objem journald a import na živém serveru zůstávají v tomto nezávislém review `NOT_VERIFIED`.

Po opravě kritérií D2–D3 stačí znovu prověřit runbook. Artefakt, příkaz a deploy nástroje není kvůli těmto nálezům nutné měnit.
