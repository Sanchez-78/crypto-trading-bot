# Re-review předregistrace EVENT screen E1/E2, rev. 3 (2026-11-26)

## Verdikt

**APPROVE_TO_RUN** — pouze pro jednorázový offline výpočet popsaný v protokolu rev. 3. Toto schválení nepovoluje změnu ani nasazení obchodního bota.

## Ověření

- Nezávisle jsem ověřil SHA-256 všech čtyř souborů připnutých v zadání rev. 3. Všechny souhlasí: protokol, skript EVENT screenu, jeho testy a převzatý loader archivů.
- Oprava pořadí je v `run()`: `check_complete()` proběhne před prvním zápisem `manifest.json`; následné soubory etap se zapisují až poté. Při chybějícím archivu se běh zastaví `NOT_EVALUABLE`.
- Kontrola úplnosti vyžaduje každou očekávanou kombinaci typu, symbolu a měsíce se stavem `OK` a neprázdným SHA-256. Stav a hash pocházejí z loaderu, který porovnává skutečný obsah archivu s kontrolním součtem.
- Nový test spouští neúplný offline běh a kontroluje, že výstupní adresář nevznikne, nebo zůstane prázdný. Prohlédl jsem test i diff; testy jsem znovu nespouštěl.
- Protokol odpovídá implementaci: výpočet je offline, nejprve vyžaduje kompletní sadu archivů a role TRAIN/TEST/HOLDOUT i potvrzovací podmínky jsou předem vymezené. Dosavadní připomínky k nulovému bootstrapu a popisné roli TRAIN zůstávají v této revizi zachované.

Skutečná data ani statistiky jsem nečetl a screening jsem nespustil. Předložený plán je po revizi 3 dostatečně fail-closed pro schválený offline běh.
