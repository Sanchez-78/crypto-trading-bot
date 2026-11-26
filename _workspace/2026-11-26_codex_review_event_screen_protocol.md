# Review předregistrace EVENT screen E1/E2 (2026-11-26)

**Verdikt: CHANGES_REQUIRED.** Neprovádět screen, dokud není opravena pravděpodobnostní statistika a dořešena validita výběru dat.

## Hlavní nálezy

1. **Jednostranné p není p-hodnota centrovaného bootstrapu.** `stats()` nejprve vytvoří bootstrapové průměry net9, jejichž střed je přibližně pozorovaný průměr, a pak počítá `(boots - net) >= net`. Tím testuje překročení dvojnásobku pozorovaného průměru, nikoli nulovou hypotézu. Správný nulový bootstrap musí v každém opakování odečíst původní průměr od denních výnosů a testovat průměr těchto centrovaných výnosů proti nule. Jinak Holm korekce i LEAD kritérium nemají deklarovanou interpretaci.

2. **Konfigurace se vybírá a vykazuje na stejných TRAIN vzorcích.** To je přípustné jako výběr, ale zobrazené TRAIN CI a p nejsou potvrzující důkaz pro vybraný vítězný konfigurák. Výsledek musí být výslovně označen jako in-sample selection/descriptive. TEST a HOLDOUT zůstávají jedinými potvrzujícími etapami.

3. **Není specifikováno ověření úplnosti očekávaných archivů.** `run()` vytvoří manifest z `fetch_archive()` a missing řádky pouze uloží, přesto pokračuje do TRAIN/TEST/HOLDOUT. Offline cache je deklarována kompletní, ale běh musí fail-closed odmítnout chybějící/mismatch archivy pro předregistrované symboly a měsíce. Jinak se stejný nedostatek může různě promítnout do výběru a výsledků.

## Ověřené části

- E1 používá pouze dokončené bary přes `closed='left'`, rozhodnutí po známém close a vstup o dvě minuty později. Holding okno kontroluje missing bary i konec bloku.
- E2 používá funding až od `calc_time + funding_interval_hours`, rozhodovací bary a vstupy odpovídají protokolu. Historie z-score nezahrnuje aktuální hodnotu.
- Blokové hranice a embargo jsou konzistentní. Výstup se pro výpočet průměrů resampluje po UTC dnech včetně dnů bez signálu.
- Holm se aplikuje na dvě rodiny v každé validační fázi. Podmínky LEAD jsou přísné a praktické.
- Grid 20 konfigurací je rozumný pro screen se dvěma předem definovanými rodinami. Net18 se reportuje jako citlivostní náklad.
- Z osmi uvedených testů jsou časování E1/E2, hold, výběr, statistické větve a falešný archiv pokryté podle zadání. Samotné pokrytí testy nenahrazuje opravu p-hodnoty.

## Před prvním výpočtem

Opravit a synteticky ověřit nulový bootstrap, přidat minimum datové integrity pro všech 476 očekávaných archivů a předregistraci označit TRAIN statistiky jako výběrové/deskriptivní. Poté připnout nové SHA-256 skriptu, testů a protokolu a požádat o re-review. Dosud nic z archivů nepočítat.

Neběžely testy ani screen. Archivy jsem neotevíral a nepřepočítával. Review vychází z protokolu a zdrojového kódu.
