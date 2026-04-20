# Fáze 2 — Návrh metrik a cílové architektury

## Úkol
Na základě opraveného stavu navrhni čistý model metrik a cílovou architekturu backend -> API -> Android.

## Skupiny metrik
Rozděl na:
- Portfolio
- Výkon
- Strategie
- Systém

## Pravidla
- každá metrika má jednoho vlastníka
- backend je source of truth pro kritické metriky
- Android nepřepočítává business-critical logiku
- live snapshot a historická analytika jsou oddělené
- formatting patří až do UI
- payload musí mít timestamp a freshness metadata

## Naming
Používej:
- `_abs`
- `_pct`
- `_ratio`
- `_count`
- `_ts`

## Cílová architektura
Preferuj:
**trading engine -> canonical event/trade store -> metric calculator -> snapshot store -> API contract -> Android mapping -> UI**

## API směr
Preferovaný payload:
```json
{
  "generated_at_ts": "...",
  "schema_version": "v2",
  "freshness": {},
  "portfolio": {},
  "performance": {},
  "strategy": {},
  "health": {}
}
```

## Povinný výstup
Vrať pouze:
1. Stručné shrnutí
2. Taxonomii metrik
3. Naming rules
4. Ownership mapu
5. Návrh API payloadu
6. Cílovou architekturu
7. Co změnit hned vs později
8. Doporučené testy a anti-regression ochrany

Buď stručný a konkrétní.
