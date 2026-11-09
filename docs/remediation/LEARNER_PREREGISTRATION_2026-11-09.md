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

## Dodatek 1 + 1b (2026-11-09, po externím auditu `_workspace/59_…` a nezávislém review)

Zapsán dřív, než byl vyhodnocen jakýkoli čerstvý obchod. Doloženo ze serveru: jediný
běh po cutoffu (07:32:36 UTC) měl `fresh_n=0`; časovač byl poté zastaven až do nasazení
slepé verze; agent si z čerstvých obchodů prohlížel jen počty a symboly. Nahrazuje kritéria výše:

- **Jediné pevné vyhodnocení.** Hodnotí se přesně prvních **1 000** obchodů vstoupených
  po cutoffu, a to až když jich existuje alespoň 1 000, od cutoffu uplynulo alespoň
  **7 × 24 h** a od vstupu 1 000. obchodu alespoň 6 h (všechny dřívější obchody jsou
  uzavřené; max. držení 900 s). První výsledek jiný než `PENDING` se zapíše do neměnného
  `/opt/cryptomaster_research/prereg_result.json` (včetně ID hodnocených obchodů) a dál
  se jen vrací; změna epochy nebo pozdější data ho nemění.
- **Slepý sběr.** Do pevného konce vrací vyhodnocení jen `PENDING` a počty. Exploratorní
  replay, report epochy i diagnostika používají jen obchody vstoupené **do cutoffu**
  (C1 = −V2 na jakékoli společné množině, takže holdout V2 nad čerstvými daty by C1
  prozradil); z čerstvé kohorty se loguje jen počet uzavřených obchodů a symbolů.
- **Kritérium.** `CONTRARIAN_CONFIRMED` jen když dolní mez Welchova 95% intervalu **i**
  dolní mez blokového bootstrapu (6h UTC okna podle vstupu, seed 20261109, 2 000
  replikací) jsou > 0. **Dodatek 1c:** hodnocená množina = prvních
  max(1 000, počet nutný k pokrytí 16 různých 6h bloků) čerstvých obchodů; do té doby
  `PENDING`. Zmrazuje se jen závěrečný verdikt (CONFIRMED / REFUTED / NOT_SHOWN),
  `INSUFFICIENT_DATA` nikdy. `CONTRARIAN_REFUTED`
  když obě horní meze < 0. Jinak `CONTRARIAN_NOT_SHOWN`.
- **Síla testu (audit, iid aproximace):** při SD ≈ 18,9 bps má N = 1 000 přibližně 80%
  sílu pro lift ≈ 3,4 bps jen pro Welchovo kritérium; souběžný požadavek na bootstrap
  a závislost obchodů skutečnou sílu snižují. Menší účinek pravděpodobně prokázán nebude.
- **Cílová populace** = obchody MAX_DATA sběru po cutoffu (limity 480/den, 30/h, cooldown
  300 s, min. modelovaný net −25 bps, 7 symbolů, CONTROL = 1,0). Výsledek platí pro ni,
  ne pro dřívější konfiguraci; srovnání P/L před/po cutoffu není účinkem učení.
- **Validace vstupu:** duplicitní ID a nekladná délka obchodu selžou; close je dostupný
  jen tehdy, když je přísně dřív než vstup.
- **V0 je aproximace** živého pravidla (globální prior, bez cohort/provenance filtru).

**Co se stane po výsledku (nahrazuje „Co následuje“):** ani `CONTRARIAN_CONFIRMED`
nepřepne hlavní politiku. Agent smí nejvýš navrhnout a po nezávislém review spustit
**omezenou replikační PAPER fázi** s předem zapsaným převodem skóre na přijetí, pevnou
délkou a zachovanou kontrolní skupinou. Trvalou změnu politiky schvaluje operátor.

## Co následuje (původní text, nahrazen dodatkem 1)

- `CONTRARIAN_CONFIRMED` → implementovat C1 jako novou verzi živého pravidla
  (`paper_source_learning_v2`) za příznakem, s testy, a nasadit; CONTROL podíl vrátit
  na 0,2, aby šlo dál měřit účinek.
- Jinak → živé pravidlo zůstává ve sběrném režimu (CONTROL 1,0); replay se počítá dál
  a nové hypotézy se registrují stejným postupem (nový dokument, nový čas registrace).

I potvrzení by znamenalo jen lepší pořadí uvnitř sbírané populace; podmíněný hrubý
pohyb vybraných obchodů se může lišit od nulového souhrnu, ale to by teprve musela
ukázat replikační fáze. Cílem je funkční učení, ne tvrzení o ziskovosti.
