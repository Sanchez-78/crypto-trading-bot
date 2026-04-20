# Claude Code — Orchestrátor s nejlepším poměrem výkon/tokeny

## Cíl

Pracuješ v existujícím projektu s:

* backend trading botem C:\\Projects\\CryptoMaster\_srv
* DB/storage vrstvou
* API/transport vrstvou
* Android aplikací C:\\Projects\\CryptoMaster\_app

Problém:

* Android app zobrazuje špatné nebo nekonzistentní metriky
* současně je potřeba navrhnout lepší architekturu metrik
* a moderní Android UI ve stylu Premium Terminal

## Důležité pravidlo

Neřeš všechno najednou v jednom velkém běhu.

Pracuj ve 3 fázích a každou dokonči samostatně:

1. Analýza a fix metrik
2. Návrh metrik a architektury
3. UI redesign a Compose implementace

V každé fázi:

* nejdřív analyzuj existující kód
* pak navrhni změny
* pak implementuj
* pak validuj
* buď stručný
* neopakuj stejné informace
* preferuj tabulky a konkrétní kód
* nepiš dlouhou teorii

## Globální pravidla

* zachovej fungující části projektu
* nepiš greenfield rewrite bez důvodu
* backend je source of truth pro kritické metriky
* Android nemá přepočítávat business-critical metriky
* UI musí být celé česky
* každá důležitá položka v UI musí mít stručný kontext
* pokud projekt používá Jetpack Compose, implementuj v Compose
* pokud ne, modernizuj v existujícím stacku

## Povinné oblasti

Metriky rozděluj na:

* Portfolio
* Výkon
* Strategie
* Systém

Naming pravidla preferuj:

* `\_abs`
* `\_pct`
* `\_ratio`
* `\_count`
* `\_ts`

## Styl UI

Použij Premium Terminal:

* tmavé grafitové pozadí
* prémiové zaoblené karty
* vysoká čitelnost čísel
* omezená sémantická barevnost
* zelená pozitivní, červená negativní, jantarová warning, modrá aktivní

## Jak postupovat

Teď čekej na konkrétní prompt pro aktuální fázi a řeš vždy jen tu jednu fázi.

