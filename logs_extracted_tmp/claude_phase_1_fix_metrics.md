# Fáze 1 — Analýza a fix špatných metrik

## Úkol
Zjisti, proč Android app zobrazuje špatné nebo nekonzistentní metriky, a implementuj fix.

## Povinný trace
Pro každou rozbitou metriku trasuj:
**trading engine -> interní stav -> DB -> API -> Android DTO -> state -> UI render**

Najdi první místo, kde se hodnota rozbije.

## Prověř hlavně
- balance vs equity
- pnl vs daily_pnl
- realized vs unrealized PnL
- percent vs fraction
- absolutní vs procentní hodnota
- stale snapshot
- stará DB pole stále čtená appkou
- špatný field binding
- různé screeny používají jiná pole pro stejný label
- timezone/day boundary
- premature rounding
- locale/string parsing
- write/read race conditions

## Implementace
- navrhni nejmenší robustní fix
- zachovej fungující části
- přidej validaci, logging a cílené testy

## Povinný výstup
Vrať pouze:
1. Shrnutí root cause
2. Findings
3. Mapu metrik:
| Metrika | UI field | API field | DB field | Backend zdroj | Jednotka | Problém |
4. Důkaz root cause:
- backend value
- DB value
- API value
- Android parsed value
- rendered value
5. Změněné soubory
6. Konkrétní kód
7. Validaci
8. Remaining risks

Buď stručný. Neřeš teď redesign UI ani finální architekturu víc, než je nutné pro fix.
