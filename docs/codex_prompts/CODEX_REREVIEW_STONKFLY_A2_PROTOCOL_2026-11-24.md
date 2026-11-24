# Re-review: protokol Stonkfly A2 po tvém auditu (Codex, 2026-11-24)

Jen audit. Report napiš česky do `_workspace/2026-11-24_codex_rereview_stonkfly_a2_protocol.md`.
Verdikt APPROVE / CHANGES_REQUIRED: je protokol připravený k jednomu běhu na dočasném izolovaném
stroji (x86-64, 8 GB, Ubuntu 24.04)?

Navazuje na `_workspace/2026-11-24_codex_a2_production_option_review.md`. Produkční varianta se
nepoužije; souhlasím s tvým zdůvodněním. Změny jsou lokální a necommitnuté.

## Opravy bodů 1–4 (`scripts/research/stonkfly_a2_network_controls.py`)

1. **Vstup vs. necitlivá síť:** jsou tři oddělené verdikty, protokol je v docstringu.
   - `input_verdict()` počítá jen ze statických metrik R1–R6 a R8 (změna podnětu proti plochému
     grafu). Výsledek je WEAK, pokud všechny směrové grafy zůstanou pod `INPUT_WEAK_PCT = 10` %
     u R1–R6 i R8 a hustá kontrola `shuffled_walk` aspoň v jednom práh dosáhne. Ta ukazuje, že
     metrika pokrytí vidí. Jinak NOT_WEAK.
   - **Upozornění k prahu:** zvolil jsem ho mezi hodnotami R1–R6 z fáze A (grafy 0,19–5,22 %,
     hustá kontrola 30,2 %). Hodnoty R8 zatím nikdo neviděl.
   - `output_verdict()` vrací `output_invariant_under_controls` (INVARIANT / VARIES) a k tomu
     `dense_control_moves_output`.
   - `conclude()` vrací kombinovaný verdikt SUPPORTS_WEAK_INPUT / NETWORK_INSENSITIVE /
     INPUT_REACHES_NETWORK / INCONCLUSIVE. Samotný neměnný výstup už nikdy neznamená slabý vstup.
2. **Fail-closed:**
   - chyba statického vstupu nebo chybějící snímek → `status: PARTIAL`, dotčené verdikty a
     kombinovaný verdikt NOT_VERIFIED;
   - selhaná sekvence → PARTIAL;
   - chyba workeru jednoho snímku se zapíše do `errors` a snímek chybí;
   - návratový kód ≠ 0.
3. **Baseline:** `STATE = baseline_fresh_checkpoint_per_worker_not_live_plastic_state` je
   v protokolu i ve verdiktu. Runbook výslovně říká, že nejde o reprodukci živého plastic
   checkpointu.
4. **Child proces:** `static_input()` má omezené `get(timeout)`, na timeout vrátí `TimeoutError` a ve
   `finally` vždy zavolá `join` → `terminate` → `kill`. Context a target jdou vyměnit kvůli testu.

## Testy

- `tests/test_stonkfly_a2_network_controls.py` (9 testů):
  - oddělené pravidlo výstupu a vstupu;
  - R8 sám vidí graf → NOT_WEAK;
  - slepá metrika → NOT_WEAK;
  - kombinovaný verdikt ve všech větvích;
  - PARTIAL/NOT_VERIFIED při chybě R8, chybějícím snímku a selhané sekvenci;
  - zaseknutý child je terminován; chyba i úspěch child procesu;
  - vzorkování R8 proti vzorci z pinnutého `visual.py`.
- Tři mutace (vypnutý fail-closed, odstraněný `terminate`, kombinovaný verdikt bez vstupní
  podmínky): každou zachytí jeden test.
- S `test_stonkfly_input_sensitivity.py`, `test_stonkfly_integration.py` a
  `test_paper_neural_context.py`: 113 passed, 1 skipped, `PROTECTED_SAME`.
- Lokální `source_signature()` = produkční `03c51fcf…` (ověřeno jen čtením).

**Ověřit:**
- Rozlišují verdikty slabý vstup od necitlivé sítě?
- Je fail-closed úplný?
- Je postup v `_workspace/2026-11-24_stonkfly_a2_runbook.md` pro izolovaný stroj dostatečný,
  hlavně kopie dat a balíku a kontrola shody prostředí?
- Je práh 10 % přijatelný s uvedenou výhradou, nebo ho mám zafixovat jinak, dokud hodnoty R8 nikdo
  neviděl?

Bez SSH, nasazení, commitu a placených zdrojů. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_a2_network_controls.py tests/test_stonkfly_input_sensitivity.py tests/test_stonkfly_integration.py tests/test_paper_neural_context.py`
s kontrolou `protected_sha.py` před a po.
