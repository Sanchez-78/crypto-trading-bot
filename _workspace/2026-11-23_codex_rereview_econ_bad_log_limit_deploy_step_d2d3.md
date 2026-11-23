# Re-review nasazovacího kroku ECON BAD po opravě D2/D3 — 2026-11-23

**Verdikt: CHANGES_REQUIRED pro kontrolní kritéria runbooku.** Původní D2/D3 jsou z větší části opravené, kód omezovače a nasazovací bajty se neměnily. Dva nové vzorce v post-checku však mohou nesprávně vyhodnotit funkční nasazení nebo podhodnotit počet odmítnutí. Na server jsem se nepřipojoval a nic jsem nenasazoval.

## Co prošlo

- `git diff d17513e^ d17513e` mění jen `AGENTS.md`, zadání/report a část „Po nasazení“ v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`. Soubor artefaktu a oba deploy nástroje mají stále SHA-256 `95e499e7…2c03`, `981c8870…7d29` a `927cc096…51c5`; příkaz k nasazení je beze změny. Stav živého serveru je `NOT_VERIFIED`.
- Příkaz v runbooku (`:105–119`) deklaruje stejné desetiminutové okno a formát `journalctl -o cat` jako podklad `baseline_journal_20261123.txt`; `grep` pro print odpovídá čtyřem úvodním mezerám ve výpisu `src/services/realtime_decision_engine.py:893`. Podklad obsahuje pouze agregované výsledky, nikoli původní journal nebo tehdy vykonaný příkaz, takže historickou totožnost příkazu nezávisle nepotvrzuji. Měřicí postup je nyní reprodukovatelně zapsaný.
- Runbook správně říká, že `total_rejects` je kumulativní, `seq` může mít mezeru a detailní řádky mají hranici nejvýš 17 na okno a marker. Mezera v `seq` není sama o sobě důvodem k rollbacku. Nový práh pro prověření journald při >10 % chybějících `seq` je provozní volba, nikoli vlastnost kódu.

## Blokující nález D4 — počet odmítnutí se musí vztáhnout ke skutečné délce úseku a dostupným souhrnům

Runbook `:128–132` označuje rozdíl `total_rejects` mezi prvním a posledním souhrnem z desetiminutového výpisu za „počet za měřený úsek“ a porovnává jej s 17 444 odmítnutími za celých deset minut před nasazením. Rozdíl ale pokrývá jen **okna mezi těmito souhrny**. Při deseti pravidelných souhrnech v desetiminutovém intervalu zahrnuje typicky devět minut; začátek a konec intervalu zůstávají mimo. Srovnání vyžaduje uvést skutečnou délku z `since_s` prvního a posledního souhrnu (nebo časů z journalu) a porovnat sazbu odmítnutí za minutu, popřípadě hodnotu přepočítanou na 600 sekund. Při méně než dvou souhrnech je tato sazba `NOT_VERIFIED`.

Alternativa „součet `window_rejects` za tatáž okna“ navíc funguje jen pro **souvislou** řadu doručených souhrnů. Při ztrátě `seq=2` mezi doručenými `seq=1, total_rejects=100` a `seq=3, total_rejects=300` je správný rozdíl 200, ale součet dostupných `window_rejects` chybějící okno neobsahuje. Runbook současně ztráty souhrnů výslovně připouští (`:133–137`). Při mezeře se proto musí použít rozdíl kumulativních součtů; součet oken lze nabídnout jen při spojitém `seq` a se stejnými hranicemi.

## Blokující nález D5 — kontrola přes kategorie v souhrnech ignoruje aktuální otevřené okno

Kritérium `:123–127` počítá `počet detailů ≤ počet různých kategorií v souhrnech × počet oken`. Souhrny ale vznikají až při **prvním dalším odmítnutí po uplynutí okna** (`src/services/realtime_decision_engine.py:809–837`). Poslední, otevřené okno v desetiminutovém výpisu tedy může vypsat první detail nové kategorie, která v žádném doručeném souhrnu ještě není. Například uzavřené okno s kategorií `a` dá souhrn; v dalším otevřeném okně přijdou první odmítnutí kategorií `a` a `b`. Tři detailní řádky za dvě okna jsou správné, ale vzorec z doručeného souhrnu zná jen `a` a stanoví mez 1 × 2 = 2. Stejný problém zesílí mezera v `seq`.

Použít konzervativní, skutečně garantovanou mez **17 × počet časových oken zasažených měřeným intervalem** pro každý marker, včetně okrajových částečných oken. Zpřesněný počet kategorií ze souhrnů nepoužívat jako tvrdé kritérium, dokud nejsou pokryta všechna okna včetně posledního otevřeného a ztracených souhrnů.

## Rozsah review

Jde jen o dokumentační změnu; testy jsem nespouštěl. Původní číselná oprava D1 i schválení kódu zůstávají platné. Žádné SSH, nasazení, restart, commit, push ani změna runtime dat. Po opravě D4/D5 stačí znovu posoudit post-check; artefakt, deploy nástroje a příkaz není kvůli těmto nálezům potřeba měnit.
