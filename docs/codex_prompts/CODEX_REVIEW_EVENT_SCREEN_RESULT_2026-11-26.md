# Review výsledku EVENT screen E1/E2 (Codex, 2026-11-26)

Jen audit, bez nového běhu a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_review_event_screen_result.md`.

Verdikty:
- **A:** platnost běhu. ACCEPT / REJECT_RUN.
- **B:** výklad. APPROVE / CHANGES_REQUIRED.
- **C:** doporučení dalšího postupu ke kladnému P/L.

## Vstupy

- Report: `_workspace/2026-11-26_event_screen_result.md`.
- Výstupy: `_workspace/event_screen_20261126/`:
  - `train.json`, `test.json`, `holdout.json`, `verdict.json`;
  - `*.started.json`;
  - `manifest.json`.
- Podpis studie: `bf9b9c4483e50876c6cf00f4a33cd16fac0a13c34cbcec9956ad60844f569b9f`.
- Skript: `scripts/research/event_shock_screen.py` (hash `fca9de04…`, ověřený před během, shodný
  s pinem rev. 3).
- Hlavní výsledek: **E1 NO_EDGE, E2 NO_EDGE**.
  - Vybrané konfigurace: `E1_k3_follow_H240` a `E2_k2_fade_H120_post`.
  - E1: net9 TEST −8,56, HOLDOUT −9,26.
  - E2: net9 TEST −27,04, HOLDOUT −15,35.
  - Hrubý pohyb ≈ 0.

## Ověř

1. **A:**
   - Odpovídá běh protokolu? Podpis, etapy `*.started.json` před výsledky, úplný manifest.
   - Je výběr na TRAIN v `train.json` v souladu s pravidlem?
2. **B:**
   - Je závěr NO_EDGE správně formulovaný?
   - Je oprávněné shrnutí „hrubá predikce ≈ 0 napříč 12+ rodinami a 3 screeny“, nebo je
     příliš silné?
3. **C:** Report navrhuje tři zbývající páky:
   1. nižší náklady přes maker plnění se skutečným modelem front;
   2. jinou informační třídu, např. order book nebo likvidace;
   3. přeformulování cíle.

   Kterou doporučuješ jako další předregistrovaný krok, nebo jinou? Je realistické, že některá
   dosáhne kladného paper P/L poctivě, bez optimalizace metrik?
