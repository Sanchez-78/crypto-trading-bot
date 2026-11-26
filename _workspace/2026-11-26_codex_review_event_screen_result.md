# Review výsledku EVENT screen E1/E2 (2026-11-26)

## A. Platnost běhu: ACCEPT

- Manifest obsahuje 476 unikátních očekávaných záznamů, všechny mají stav `OK` a 64znakový SHA-256; `missing` je prázdné.
- Nezávisle jsem přepočítal studijní podpis z aktuálního skriptu a manifestu. Výsledek je `bf9b9c4483e50876c6cf00f4a33cd16fac0a13c34cbcec9956ad60844f569b9f`, shodný s reportem i všemi etapami.
- `train`, `test` a `holdout` mají každý jeden marker `*.started.json` před výsledným JSON; podpisy všech etap souhlasí. Výběr TRAIN odpovídá maximu net9 mezi způsobilými konfiguracemi: E1 `E1_k3_follow_H240` (−4,63 bps), E2 `E2_k2_fade_H120_post` (−7,56 bps).
- Výstupy dávají `NO_EDGE` pro obě rodiny podle předem stanovených podmínek. E1: net9 −8,56 bps v TEST a −9,26 v HOLDOUT; E2: −27,04 a −15,35 bps. Výběr i potvrzovací výsledky jsou oddělené podle protokolu.

Audit ověřil vnitřní konzistenci uloženého manifestu, podpisů a etap; znovu jsem nečetl 476 archivů ani nespouštěl výpočet. Platnost proto přijímám na základě schváleného protokolu a uložených artefaktů.

## B. Výklad: APPROVE s upřesněním rozsahu

`NO_EDGE` je správný závěr pro tyto dvě předem vymezené rodiny, tento výběr, data, horizonty a nákladový scénář 9 bps. Výsledky podporují, že v těchto testech hrubý průměr nedosáhl nákladů. U E1 jsou hrubé průměry TEST/HOLDOUT +0,44/−0,26 bps; u vybrané E2 −18,04/−6,35 bps.

Závěr „více než 12 rodin ve 3 nezávislých testech“ je příliš silný, pokud „nezávislé“ znamená nezávislé replikace: hypotézy a screeny mohou sdílet symboly, období, zdroje cen a podobné výběrové mechanismy. Bez výslovného auditu překryvů je přesnější říci „více než 12 testovaných rodin napříč třemi screeningovými projekty“. Stejně tak výsledek neprokazuje, že veřejná cenová data obecně neobsahují predikovatelnou informaci; omezuje pouze testovanou sadu pravidel a zvolený cost-wall model.

„Ani nejlepší TRAIN konfigurace nebyla po nákladech kladná“ je přesné jako popis výběrového bloku, ne jako potvrzující test. TRAIN byl použit k výběru, a proto jeho výsledek nelze počítat jako další nezávislé potvrzení.

## C. Doporučení

Jako bezprostřední další krok volím **3: přeformulovat výzkumný cíl**, nikoli hledat další cenové prahy. Výsledky zatím nedávají podklad k tvrzení o kladném P/L; vhodné je oddělit cíl „učit se a měřit“ od cíle „prokázat edge“ a pro každý stanovit vlastní předem dané metriky a stop podmínky.

Pokud zůstane strategickým cílem kladné P/L, nejbližší empirická cesta je **2: nová informační třída**, ale první krok má být sběr a audit pokrytí order-book/liquidation dat, bez obchodní změny. Maker model (1) může snížit nákladovou laťku jen při realistickém modelu fronty, pravděpodobnosti fillu, adverse selection a poplatků; bez toho hrozí optimistický replay. Žádná z cest nemá zatím prokázanou pravděpodobnost úspěchu.

Toto doporučení nemění bota ani měřicí okno a není tvrzením o ziskovosti.
