# Follow-up 1 — Data consistency + source of truth

Řeš jen data consistency a source of truth.

## Úkol
- projdi projekt
- najdi metric calculation, server live state, Firebase writes/reads, snapshoty, API, Android DTO/state/UI mapping
- proveď trace:
  **server live -> Firebase / aggregate / snapshot -> API -> Android DTO -> state -> UI**
- najdi root cause nekonzistence
- navrhni a implementuj nejmenší robustní fix

## Kontroluj hlavně
- balance vs equity
- live equity vs snapshot equity
- realized vs unrealized PnL
- daily vs total PnL
- percent vs fraction
- absolute vs percent
- stale Firebase snapshot
- timestamp inconsistency
- timezone/day-boundary
- ordering obchodů a incidentů
- Android field mapping
- NaN / null fallbacky

## Povinný výstup
1. Root cause shrnutí
2. Findings
3. Source-of-truth model
4. Mapu metrik:
| Metrika | Zdroj | Kde se rozbíjí | Fix |
5. Změněné soubory
6. Konkrétní kód
7. Validaci

Neřeš ještě redesign screenů.
