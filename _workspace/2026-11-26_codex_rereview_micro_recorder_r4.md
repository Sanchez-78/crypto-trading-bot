# Re-review micro-recorderu rev. 4 (2026-11-26)

## Verdikt

- **A — `stop-tick`: APPROVE**
- **B — `preflight` + `install`: CHANGES_REQUIRED**

Review byl read-only; na server jsem se nepřipojil, nic nenasadil a testy znovu nespouštěl. Nezávisle jsem ověřil SHA-256 všech šesti souborů připnutých v zadání; všechny souhlasí.

## A — `stop-tick`: APPROVE

Ověření rozbitého stavu se nyní opakuje po forenzním čtení a těsně před `disable --now`. PID i nalezená cesta FD musí souhlasit s prvním ověřením. Při změně skript končí bez vypnutí; originální log ponechává. Test pokrývá změnu PID mezi ověřeními. Samostatný krok A lze spustit podle připnutého skriptu.

## B — `preflight` + `install`: CHANGES_REQUIRED

Předchozí problémy s přesměrováním prostředí, symlink cestami, zápisem v preflightu a mazáním cizích dočasných souborů jsou opravené. Umístění přes `ln` také nepřepisuje existující cíl. Zůstává však okrajový případ v rollbacku:

- `place()` odmítne cílový soubor, který vznikl po preflightu, ale `rollback()` odstraňuje finální APP/unit soubory pouze podle shody SHA-256. Pokud souběžná operace vloží do cíle soubor se stejným hashem jako připnutý artefakt, `ln` správně selže, následný rollback ale tento cizí soubor smaže. Hash potvrzuje obsah, nikoli vlastnictví souboru tímto během.
- Ukládejte si, které finální cesty skutečně vytvořilo úspěšné `ln` v tomto běhu, a rollbackem odstraňujte pouze tyto cesty; nebo použijte jiný atomický vlastnický marker. Přidejte test, v němž se mezi preflightem a `ln` objeví cíl s přesnými připnutými bajty a po rollbacku musí zůstat.

Stávající test „cíl vznikl po preflightu“ používá cizí textový obsah, proto tento případ nezachytí. Po opravě a cíleném testu lze B znovu schválit.

Oddělené pořadí fází je správné: schválené A se může provést samostatně; B zůstává neschválené do dalšího review. `preflight`, instalace, ověření po 10 minutách a po 24 hodinách zůstávají oddělené.
