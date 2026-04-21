# Follow-up 4 — Obchody + DetailObchodu

Řeš jen záložku Obchody a detail obchodu.

## Požadavky
### Trade list
- timestamp desc default
- filtry: pár, období, profit/loss, long/short, exit reason
- bohaté list karty

### List karta má ukazovat
- pár
- BUY/SELL
- výhra/prohra
- PnL
- entry/exit
- režim trhu
- exit reason
- timestamp

### Detail obchodu
- open timestamp
- close timestamp
- duration
- entry
- exit
- size
- fees
- realized pnl
- realized pnl %
- exit reason
- confidence při vstupu, pokud existuje
- regime při vstupu, pokud existuje
- EV při vstupu, pokud existuje
- další relevantní trading info

## Pravidla
- vše česky
- timestampy viditelné a srozumitelné
- zachovat trading DNA
- neudělat z toho obyčejný finance list

## Povinný výstup
1. Struktura Obchodů
2. Trade card vs detail card
3. Změněné soubory
4. Konkrétní Kotlin/Compose kód
5. Validace řazení a filtrů
