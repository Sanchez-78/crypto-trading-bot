# Review předregistrace nového zdroje signálu: EVENT screen E1/E2 (Codex, 2026-11-26)

Jen audit, bez běhu screenu, stahování dat a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_review_event_screen_protocol.md`.
Verdikt: **APPROVE_TO_RUN / CHANGES_REQUIRED**.

## Kontext

Operátor požaduje nový zdroj signálu, protože současné signály mají hrubý pohyb ≈ 0 proti nákladu
9 bps (`_workspace/2026-11-24_wr_pl_decline_analysis.md`, aktualizace 2026-11-26). Dřívější rodiny
jsou vyloučené, mimo jiné screen 64 (H1–H7 NO_EDGE). Charter označuje událostní a režimové
obchodování jako dosud nevyzkoušené. Screen je pouze offline. Bot ani měřicí okno (do 2026-12-02)
se nemění.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_event_screen_protocol.md` | `32f513772e791a555c62149c372a5e6a162a39ddb5ac41320a26e80589e7355b` |
| `scripts/research/event_shock_screen.py` | `5989643473dc51c4332cc659944cac0ef3096ba54803e8777e2c580969dd9f30` |
| `tests/test_event_shock_screen.py` (8 testů) | `1e2950d2b953bbfcfe69738862017bae4d48ca1e7d1efe783d300fe208b3a920` |
| `scripts/research/futures_flow_screen.py` (beze změny, jen loadery) | `a393d07682630136efd5c29ed6cd6bafbd0cf9b595b32b5c5fff9b5eb1c1328f` |

Žádná data jsem zatím nestahoval a žádnou statistiku TRAIN/TEST/HOLDOUT jsem nepočítal.

## Ověř

1. **Look-ahead:**
   - E1: r5 a v5 z dokončených barů, z-skóre `closed="left"`, vstup t+2m;
   - E2: dostupnost fundingu od `calc_time + interval`, rozhodovací bary T−62m/T−1m;
   - R_H od open vstupu po close H-tého baru.
2. **Hranice:** okno uvnitř bloku, embargo prvního dne, zahřátí bez vzorků, bez souběhu na symbol.
3. **Výběr a zmrazení:** jen podle TRAIN (≥ 200 vzorků), `sealed_stage` s podpisem skriptu a dat,
   Holm přes 2 rodiny.
4. **LEAD kritéria:** jsou dost přísná proti náhodě a betě? Kontroluje se BTC 24h UP/DOWN, poloviny
   TEST a koncentrace symbolů.
5. **Rozpočet:** je 20 konfigurací přiměřený? Chybí podle tebe nějaká zjevná kontrola, třeba net18
   jako požadavek nebo efektivní n u překrývajících se událostí?
6. **Testy:**
   - pokrývají časování a dostupnost (E1, E2);
   - pokrývají hranici bloku a chybějící bar;
   - pokrývají statistiku a výběr;
   - obsahují integrační test na falešném archivu.

Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_event_shock_screen.py` a
`protected_sha.py` před a po.
