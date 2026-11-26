# Review pravidla po měřicím okně (2026-11-26)

## Verdikt: CHANGES_REQUIRED

Nezávisle jsem ověřil SHA-256 připnutého evaluátoru a testů; oba odpovídají zadání. Výsledky okna jsem nepočítal, testy jsem znovu nespouštěl a k databázi ani serveru jsem se nepřipojil.

### 1. Porovnání musí být proti aktuálnímu prahu −25 bps

V `evaluate()` je `selected` definováno jako `predicted >= cut`, ale `dropped` jako všechny ostatní řádky. Při kandidátu −10 proto „dropped“ obsahuje také obchody s predikcí pod −25, které už současný práh vyřadil; u kandidáta 0 stejně. Podmínka `selected − dropped > 0` tak může být splněna díky obchodům, které by změna prahu vůbec nově nevyřadila.

Pro každý přísnější řez musí být relevantní základní populace obchody s platnou predikcí `>= -25`. Z ní vyberte `predicted >= cut`; nově vyřazené jsou pouze `-25 <= predicted < cut`. Porovnávejte tyto dvě skupiny. Přidejte test s velmi ztrátovými obchody pod −25 a ověřte, že neovlivní oprávněnost kandidáta.

### 2. Počet 1 000 a ramena musí odpovídat živé bráně

Evaluátor počítá minimum 1 000 ze všech uzavřených obchodů a do `dropped` zahrnuje i řádky bez predikce. Produkční persistovací cesta ale ukládá `predicted_net_edge_bps` pouze pro `explore_bucket == "P0_8_PLUS_EVIDENCE_COLLECTION"` (`local_persistent_cache.py`, `_prediction_bps`). Ostatní obchody nejsou populací, na kterou se `PAPER_PROBE_MIN_NET_BPS` aplikuje.

Oddělte obchodní populaci, na niž brána skutečně působí, od ostatních obchodů. Počet pro `INSUFFICIENT_DATA` i obě bootstrapová ramena počítejte jen z této populace; chybějící predikce reportujte odděleně a nepovažujte je za nově vyřazené přísnějším prahem. Jinak mohou nesouvisející obchody splnit minimum nebo uměle zhoršit srovnávací rameno.

### 3. Dva kandidátní prahy znamenají dvě kontroly

Pravidlo vyhodnotí −10 i 0 bps na stejném okně a vybere některý, pokud jeho samostatný 95% dolní bootstrap limit rozdílu překročí nulu. Bez korekce nejde o celkovou 5% chybu pro rozhodnutí „některý práh je způsobilý“. Použijte předem zapsanou korekci pro dvě hypotézy (např. Holm nebo simultánní bootstrap), případně označte tento krok výslovně jako průzkumný a neprovádějte podle něj automatickou změnu bez dalšího review.

### 4. Testovací časový override obchází čekací pojistku

CLI přijímá `--now` a používá ho přímo k rozhodnutí, zda okno už dozrálo. Nápověda „tests only“ použití na produkci nevynucuje. Odstraňte tento CLI override a testujte čas přes monkeypatch/injekci, nebo jej dovolte jen v explicitním test režimu, který produkční spuštění odmítne. Jinak lze omylem vyhodnotit neuzavřené obchody ještě před `END + 1800 s`.

### Poznámky k interpretaci a následné akci

- Shoda řezu s vyšším průměrným net bps sama nezaručuje vyšší WR. Skript WR vykazuje, ale nepoužívá ho jako podmínku. Tvrzení, že zpřísnění WR zvýší, proto formulujte jako hypotézu, pokud pro něj nepředregistrujete samostatné pravidlo.
- Protokol správně popisuje výsledek jako prediktivní třídění, ne kauzální účinek prahu. Ani případné `TIGHTEN` samo neprokazuje, že změna produkčního PAPER prahu zlepší P/L. Toto review neschvaluje restart ani změnu konfigurace na základě dosud neviděného výsledku; po opravě pravidla lze předem schválit jeho vyhodnocení a následný konkrétní postimage posoudit samostatně.

Po opravách porovnání s baseline populací, kohorty brány, násobného testování a časového override požádejte o re-review. Do té doby po konci okna pouze vypočtěte/uložte výsledek k review; neměňte práh automaticky.
