# Re-review instalace micro-recorderu, rev. 5 (2026-11-26)

## Verdikt B: APPROVE_TO_DEPLOY

Schvaluji pouze fáze `preflight` a `install` podle připnutého rev. 5 skriptu a následná ověření po 10 minutách a po 24 hodinách. Toto review samo nic nenasazuje. Krok A (`stop-tick`) je již proveden; znovu jsem ho nehodnotil ani nekontroloval na serveru.

## Ověření

- Nezávisle jsem ověřil SHA-256 všech šesti souborů uvedených v zadání rev. 5. Všechny odpovídají pinům.
- Oprava případu z rev. 4 je úplná: automatický rollback vede seznam cílů vytvořených úspěšným `ln` v tomto běhu; cíl, který vznikne souběžně a způsobí selhání `ln`, do seznamu nepřidá. Automatický rollback proto cizí soubor ponechá i tehdy, když má přesně připnutý obsah. Ruční rollback je samostatná explicitní fáze.
- Automatický rollback vypíná unit jen tehdy, když ji vytvořil tento běh; maže jen jím vytvořené finální cíle a dočasné soubory. Cizí cíl se stejným hashem zůstává nedotčený.
- Potvrzuji také dříve opravené kontroly: pevné produkční cesty, odmítnutí symlinkovaných rodičů, zápis bez přepsání, preflight bez bytecode zápisu, ověření procesu `tick-recorderu` znovu před vypnutím a rollback při chybách instalace.
- Nezávislý test ani serverový příkaz jsem nespustil. Kontroloval jsem připnutý kód, testy a deklarované výsledky záznamu.

Fáze zůstávají oddělené: nejprve `preflight`, pak `install`; při selhání instalace se provede automatický rollback. Po úspěchu následuje `verify` po 10 minutách a po 24 hodinách. Výsledky sběru jsou výzkumná data, ne důkaz edge ani P/L.
