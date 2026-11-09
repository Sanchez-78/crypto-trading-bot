# Předregistrace: protisměrné učení (2026-11-09)

## Co bylo vidět (stará data, NEPOUŽÍVAT jako důkaz)

Walk-forward replay 10 předem daných variant učení (`src/services/learner_replay.py`,
`scripts/research/learner_replay_report.py`) na 915 obchodech epochy od 25. 9.:
všechny varianty mají na holdoutu (posledních 40 %) **záporný** lift — kontexty
s lepší nedávnou historií dopadají hůř. Současné pravidlo V0: holdout lift −3,50 bps
[−7,52; +0,51]; bez zapomínání (V2) −4,41 [−8,42; −0,40]. Diagnostika
`learning_diagnostics.py`: odhad učení vs výsledek ρ = −0,11 (n = 752).

Protože tato hypotéza vznikla pohledem na tato data, smí se ověřit **jen na nových**.

## Hypotéza (jediná, pevná)

`C1_contrarian` = odhad V2 (klíče source/symbol/regime/side, bez zapomínání,
prior weight 5) s opačným znaménkem. Na obchodech **vstoupených po čase registrace**
má horní polovina podle C1 vyšší průměrný net než dolní polovina.

- Registrace = okamžik nasazení `PAPER_LEARNING_CONTROL_FRACTION=1.0` (zapsán do
  `/opt/cryptomaster_research/prereg_after`). Od té doby bot pouští všechny kandidáty,
  takže hodnocená data nejsou zkreslena živým filtrem.
- Starší obchody slouží jen jako historie pro odhady, nikdy se nehodnotí.
- Minimum 300 čerstvých obchodů. Výsledek: `CONTRARIAN_CONFIRMED` (dolní mez liftu > 0),
  `CONTRARIAN_REFUTED` (horní mez < 0), jinak `CONTRARIAN_NOT_SHOWN`.
- Žádné další varianty, prahy ani podmnožiny se na těchto datech nehledají.

## Co následuje

- `CONTRARIAN_CONFIRMED` → implementovat C1 jako novou verzi živého pravidla
  (`paper_source_learning_v2`) za příznakem, s testy, a nasadit; CONTROL podíl vrátit
  na 0,2, aby šlo dál měřit účinek.
- Jinak → živé pravidlo zůstává ve sběrném režimu (CONTROL 1,0); replay se počítá dál
  a nové hypotézy se registrují stejným postupem (nový dokument, nový čas registrace).

Kontrarián nevytvoří hrubý edge: i při potvrzení jde o výběr uvnitř obchodů, jejichž
hrubý pohyb je dosud kolem nuly. Cílem je funkční učení, ne tvrzení o ziskovosti.
