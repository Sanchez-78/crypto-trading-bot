# Re-review pravidla měřicího okna – R3

**Verdikt: APPROVE_RULE**

Zkontroloval jsem zadání R3, protokol, implementaci a příslušné testy. SHA-256 skriptu a testů odpovídají hashům uvedeným v zadání:

- `scripts/research/threshold_window_eval.py`: `1f999cc1c0a5e8d9eaefbaa2cbcdc5dbe623ac1efcc4e4c78816a5a36f26d4d0`
- `tests/test_threshold_window_eval.py`: `0533d5aebe30f1ff7c508597e732577657660bf88d0a24715f891f6c343b0755`
- `_workspace/2026-11-26_threshold_window_decision_rule.md`: `cf487fbb770a573d64804ad157c2a9dc22069e68c02245b2e3037c8ac55bb3c8`

## Zjištění

- Holmova korekce vždy zahrnuje oba kandidátní prahy. Netestovatelný kandidát zůstává v rodině jako `None`, nelze jej schválit a druhému kandidátu zůstává odpovídající přísnější hranice. Implementace i integrační scénáře pro prázdné pásmo −10 a hodnoty p = 0,02 / 0,01 odpovídají protokolu.
- Chybějící či neplatné `pnl_usd` se nezaměňuje za nulu. USD souhrny a profit factor se označí jako nevyhodnotitelné a uvede se počet chybějících hodnot; rozhodnutí vychází z `pnl_pct`.
- Rozhodovací populace je omezena na obchody, které současný práh −25 bps pustil a mají predikci. Minimum, porovnání vyřazeného pásma i korekce jsou konzistentní s protokolem.
- Časová pojistka zůstává bez CLI přepínače pro její obejití. WR je popisný údaj, nikoli rozhodovací podmínka. Při výsledku TIGHTEN se automatická změna konfigurace neprovádí.

Náhrada `None` hodnotou `1.0` v Holmově rodině by v tomto rozsahu nezměnila rozhodovací výsledek: p-hodnota 1,0 nemůže být zamítnuta a stejně jako `None` zůstává v počtu hypotéz. To není důvod k blokaci; testy nemusí tvrdit, že tuto sémanticky ekvivalentní reprezentaci rozlišují.

## Rozsah schválení

Schválen je předem zapsaný postup a jeho offline vyhodnocovací skript pro jednorázové vyhodnocení po konci okna. V tomto review jsem nespouštěl skript nad produkčními ani skutečnými daty a neověřoval výsledek měřicího okna. Toto schválení nepovoluje změnu prahu ani nasazení konfigurace. Pokud výsledek doporučí TIGHTEN, konkrétní změna a její postimage vyžadují samostatné review.
