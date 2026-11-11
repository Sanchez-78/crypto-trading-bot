# C2 — podmíněný návrh opakovacího PAPER testu učení

**Stav: DRAFT / NEAKTIVNÍ.** Vytvořeno 2026-11-11 před výsledkem C1. Tento dokument nemění bota, env, cutoff ani rozhodovací politiku. Není to hotová předregistrace ke spuštění: položky označené `UZAVŘÍT PŘED STARTEM` se smějí doplnit jen jednou, před první C2 příležitostí, po nezávislém review implementace i statistického protokolu. Čerstvé výsledky C1 se do té doby nečtou.

## Podmínka vstupu

C2 lze připravit k aktivaci pouze když existuje jediný zmrazený C1 výsledek s ověřeným `PROVENANCE` (hash manifestu i přesných bajtů výsledku), jeho verdikt je `CONTRARIAN_CONFIRMED` podle předregistrace a `cost_and_learning_review.py` odděleně oznámí, co je prokázané o řazení a co o post-cost zisku. Při `CONTRARIAN_REFUTED`, `CONTRARIAN_NOT_SHOWN`, `PENDING`, `INSUFFICIENT_DATA` nebo `NOT_VERIFIED` se C2 nespouští. Ani `CONFIRMED` nepovoluje automatické nasazení politiky.

C2 začne až po samostatně reviewované opravě svíček a stabilizačním ověření nové kohorty. Nasazení cache, změna nákladů a začátek C2 nesmějí proběhnout jako jedna nerozlišitelná změna. Před C2 se zmrazí verze kódu, rendereru vstupů, cost modelu, exit/risk profilu, symbolů, časový `cohort_start_ms` a hash konfigurace. C1 data a C2 data se neslučují.

## Otázka a předběžný design

Jediná primární otázka: **zlepší použití předem definovaného skóre C1 pro přijetí kandidátů čistý PAPER výsledek oproti současnému režimu bez adaptivního odmítání, po stejných nákladech a při stejné risk/execution cestě?** Kladný C1 lift mezi dvěma polovinami sám o sobě není důkaz této otázky ani kladného P/L.

Předběžná politika: skóre `C1_contrarian = -V2_no_decay` s klíči `(source, symbol, regime, side)` a prior weight 5 se počítá výhradně z outcome obchodů uzavřených **přísně před** časem dané příležitosti. Před C2 se jednou vypočte práh jako medián *skóre* zmrazené C1 hodnocené množiny, bez optimalizace podle jejích P/L. Léčebné rameno přijme pouze kandidáta se skóre `> práh`; rovnost, chybějící nebo neplatné skóre zamítne. Kontrolní rameno skóre měří, ale neodmítá podle něj. V obou ramenou zůstávají stejné generátory, cost model, P0/risk, sizing, paper executor a exit engine. Není povolen bootstrap bypass, přímá cesta ke Stonkfly executorům ani REAL objednávky. **UZAVŘÍT PŘED STARTEM:** prokázat, že živé skóre a point-in-time pravidla přesně odpovídají uvedené definici; hash kalibračního artefaktu a pravidlo chybějících kontextů.

Kvůli sdílené kapacitě portfolia je pracovní návrh **switchback randomizace 6h UTC bloků**, nikoli označení přijaté podskupiny jako „A/B testu“. Sousední páry bloků dostanou v poměru 1:1 léčbu/kontrolu deterministickou permutací ze seedu zapsaného před startem. Při změně ramene se nové vstupy v prvních 15 minutách pozastaví, aby skončily pozice z předchozího bloku (současné maximum držení 900 s); pokud zůstanou otevřené, nový blok se neobchoduje a událost se zaznamená. Žádné pozice se kvůli testu násilně nezavírají. Toto pravidlo vyžaduje review dopadu na populaci a implementaci, předem neplatí v živém botu.

Všechny kandidátní příležitosti, vzniklé před policy filtrem, dostanou stabilní `decision_id`, čas, symbol, profil, skóre, přiřazený blok/rameno a důvod každého zamítnutí. Odděleně se počítají kandidáti, po policy filtru přijatí, risk-admitted, otevřené paper pozice a uzavřené obchody. Nepřijatý kandidát není fiktivní obchod ani closed-trade evidence. Duplicitní decision ID se nepočítá dvakrát. Pokud skutečná živá cesta tyto identity neumí doložit, C2 se nespustí.

Primární estimand má být rozdíl **čistého PAPER výnosu portfolia za randomizovaný 6h blok, v bps z kapitálu na začátku bloku**, podle přiřazeného ramene (intention-to-treat). Nulový počet obchodů v bloku je platný nulový výsledek bloku, ne uměle vytvořený obchod. Souběžně se reportuje net na původní kandidátní příležitost a net na skutečně uzavřený obchod; tato dvě čísla se nesmějí zaměňovat. Rozdíly se vyhodnocují po párech bloků, s intervalem z předem dané blokové metody. **UZAVŘÍT PŘED STARTEM:** přesná definice kapitálu a účtování pozic přes hranici bloku, minimální ekonomicky zajímavý účinek ve stejných jednotkách, pevný počet bloků nebo časový konec a konzervativní power odhad z dat dostupných před C2. Staré „3 bps na obchod“ z osnovy nelze bez převodu použít jako „3 bps na blok“.

Skórovací stav může být společný pro obě ramena a učit se jen ze skutečně uzavřených PAPER obchodů. To testuje **použití filtru v prostředí se společným learnerem**, ne izolovaný účinek samotného algoritmu učení: léčba může změnit budoucí tréninkovou množinu. **UZAVŘÍT PŘED STARTEM:** nezávislé statistické review této interference a předem určené zacházení s ní. Pokud nelze společný stav interpretovat, C2 se přepracuje před aktivací; nevytváří se druhý trading runtime ani executor.

## Pevný konec a interpretace

Před první příležitostí se nevratně uloží seed, blokový rozvrh, start/konec, účtovací jednotky, minimální účinek, pravidla chyb a hash protokolu. Výsledek se otevře **jednou po pevném konci a po uzavření všech pozic**. Žádné průběžné testování účinku, prodloužení do zisku, hledání nejlepšího prahu nebo podskupiny. Provozní safety metriky (crash, stale data, risk, disk) se smí kontrolovat bez outcome splitu; safety stop znamená `INCONCLUSIVE`, ne ad hoc náhradní období.

Závěrečný report uvede počet a pokrytí bloků, počty všech jmenovatelů, gross/net, fees, spread/slippage/funding či borrow podle produktu, WR podle existující definice bota (WIN až při net > +5 bps), PF, max DD, timeout, holding time a rozpad po symbolech/režimech jako **sekundární**. Primární závěr o rozdílu ramen a samostatný závěr o kladném post-cost EV léčebného ramene se vyhodnotí odděleně. Uvedou se i intervaly a chybějící data. Pozitivní C2 by stále nebylo povolením REAL tradingu ani trvalé změny politiky.

## Brány před případným spuštěním

1. Ověřený C1 `CONTRARIAN_CONFIRMED` a verifikovaný cost review; jinak **STOP**.
2. Oprava svíček v nové kohortě, nezávislé review a stabilní data; cost model finálně zvolený a stejný v obou ramenou.
3. Uzavřené položky `UZAVŘÍT PŘED STARTEM`, předstartovní power odhad a neměnný protokol bez C2 outcomes.
4. Implementace v jediném existujícím PAPER runtime, nezávislé review přesného diffu, testy randomizace/attribution/capacity/restartu, rollback a výslovné schválení operátorem.

Do splnění všech bran zůstává C2 pouze dokumentem. Žádné env příznaky ani služby tímto návrhem nevznikají.
