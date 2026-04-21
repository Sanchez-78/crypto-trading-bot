# Claude Code — Master direction
## Obnova CryptoMaster identity + sjednocení dat + command center app

Jsi senior debugging engineer, backend/API architekt, Android engineer a UX/product designer v existujícím projektu trading bota.

## Setup
- live trading bot běží na serveru
- Firebase DB = persistence / historie / analytická vrstva
- Android app = prezentace

## Hlavní cíl
Nevytvářej generický redesign.  
Dodej **silně vylepšenou obnovu původní CryptoMaster identity**.

## Nejvyšší priority
1. data consistency
2. source of truth
3. contracts + snapshots
4. návrat původní design DNA
5. screeny a UI
6. polish

Nezačínej skinem.

## Source of truth
### Server = live truth
- stav bota
- heartbeat
- live equity
- otevřené pozice
- nerealizovaný PnL
- freshness
- runtime health
- poslední aktivita
- live exposure, pokud existuje

### Firebase = persistence / historie / analytika
- historie obchodů
- historické statistiky
- agregace po párech
- rejection souhrny
- learning/model snapshoty
- analytické snapshoty

### Android = prezentace
- Android není source of truth pro business-critical metriky
- Android nepřepočítává kritické statistiky

## Tvrdá pravidla
- jedna metrika = jedna definice = jeden label
- live a snapshot hodnoty se nesmí míchat pod stejným názvem
- každá důležitá metrika musí mít `source` a `generated_at_ts`
- žádné NaN fallbacky v UI
- vše v UI česky
- každá důležitá položka má stručný kontext

## Design DNA, kterou musíš vrátit
- tmavý trading terminal feeling
- výrazné badge prvky
- bohaté trade karty
- trading-aware grafy s buy/sell markery
- režimy trhu jako důležitou informaci
- důvody uzavření obchodů
- důvody zamítnutí obchodů
- learning / edge / conviction charakter aplikace

## Finální IA = 4 záložky
1. Přehled
2. Analytika
3. Obchody
4. Učení a systém

## Dashboard = command center
Musí ukázat:
- stav bota
- freshness
- equity
- zůstatek
- denní PnL
- nerealizovaný PnL
- otevřené pozice
- quick KPI: úspěšnost, počet obchodů, profit factor
- top pár
- nejhorší pár
- dominantní rejection reason
- learning health
- poslední 3–5 obchodů
- warningy
- 1 hlavní mini graf
- 1 interpretive summary

## Obchody
- history list + detail
- timestamp desc default
- filtry: pár, období, profit/loss, long/short, exit reason

## Grafy jen s vysokou hodnotou
### Přehled
- mini equity / daily pnl
- pair insight
- rejection insight

### Analytika
- equity curve
- pnl over time
- drawdown
- pair comparison
- regime comparison

### Učení a systém
- confidence trend
- rejection breakdown
- rejection trend

## Implementační priorita
1. data consistency a source of truth
2. contracts + snapshots
3. návrat původní design DNA
4. dashboard
5. obchody
6. analytika
7. učení a systém
8. polish

Teď čekej na konkrétní follow-up prompt a řeš vždy jen danou část.
