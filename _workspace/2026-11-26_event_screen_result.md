# EVENT screen E1/E2: výsledek (Claude, 2026-11-26)

Protokol rev. 3 (`_workspace/2026-11-26_event_screen_protocol.md`), schválen
`_workspace/2026-11-26_codex_rereview_event_screen_protocol_r3.md` (APPROVE_TO_RUN).

## Běh

- Skript má hash `fca9de04…`, ověřený před během.
- Jeden běh offline nad 476/476 ověřenými archivy (2024-01 až 2026-10), `missing_archives` je
  prázdné, rc 0.
- Výstupy jsou v `_workspace/event_screen_20261126/`:
  - `train.json`, `test.json`, `holdout.json`, `verdict.json`;
  - `*.started.json`;
  - `manifest.json`.
- Podpis studie: `bf9b9c44…`.
- **Verdikt: E1 = NO_EDGE, E2 = NO_EDGE.**

## TRAIN (výběrové, jen popisné)

- Ani nejlepší z 20 konfigurací nemá kladné net9.
- Nejvyšší hrubý pohyb mají E1 „follow“ s držením 240 min (+4,4 bps hrubě, net9 −4,6, CI
  [−13,1; +3,6]).
- Varianty „fade“ jsou zrcadlem (−4,4 hrubě).
- E2 má hrubě nejvýš +1,4 bps.
- Vybráno: `E1_k3_follow_H240` (n 6 133) a `E2_k2_fade_H120_post` (n 851).

## Potvrzující bloky

| | blok | n | hrubě | net9 [95% CI] | net18 | Holm p | WR net9 |
|---|---|---:|---:|---|---:|---:|---:|
| E1 | TEST | 3 240 | +0,44 | −8,56 [−21,45; +4,89] | −17,56 | 1,0 | 43,9 % |
| E1 | HOLDOUT | 2 676 | −0,26 | −9,26 [−18,09; −0,56] | −18,26 | 1,0 | 43,3 % |
| E2 | TEST | 368 | −18,04 | −27,04 [−42,87; −11,08] | −36,04 | 1,0 | 38,0 % |
| E2 | HOLDOUT | 261 | −6,35 | −15,35 [−24,79; −5,58] | −24,35 | 1,0 | 40,6 % |

- **E1 TEST** podle trhu BTC: DOWN +2,31 (n 1 684), UP −20,32 (n 1 556). Obě poloviny jsou
  záporné.
- **E1 HOLDOUT:** DOWN −11,58, UP −6,97.
- **E2** je záporné ve všech skupinách.

Nesplněná kritéria LEAD jsou ve `test.json` a `holdout.json` (`lead_failures`). Nesplněno je mimo
jiné net9 > +3, CI > 0 a Holm.

## Závěr

Ani reakce na cenový šok s objemem (fade i follow, 1–4 h), ani obchodování kolem extrémního fundingu
nemá na datech 2024–2026 hrubý pohyb, který by pokryl náklady. **Hrubý pohyb je ≈ 0 bps**, stejně jako
u současných signálů bota a dřívějších screenů. Mezi vyloučené rodiny přibývají E1 a E2.

Co z toho plyne pro cíl kladného P/L (návrh k review, nic se neimplementuje):
- Na 7 likvidních symbolech a horizontech minut až hodin opakovaně vychází hrubá predikce ≈ 0. Je to
  už 12+ rodin a 3 nezávislé screeny.
- Další ladění cenových a událostních pravidel nemá vysokou předchozí pravděpodobnost úspěchu.
- Kladné P/L v paper simulaci se tak nedá poctivě vyrobit z dostupných veřejných cenových dat
  běžnými signály.
- **Zbývající poctivé páky jsou strukturní:**
  - nižší náklady (maker plnění se skutečným modelem front);
  - jiná informační třída (např. order book nebo likvidace v reálném čase, které tick_recorder
    nesbírá dostatečně dlouho);
  - nebo přeformulování cíle.

  Každá z nich je samostatný projekt s vlastní předregistrací.
