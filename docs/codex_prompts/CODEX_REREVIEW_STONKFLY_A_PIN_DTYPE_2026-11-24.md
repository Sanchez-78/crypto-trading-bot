# Re-review: Stonkfly fáze A, kontrola pinu včetně dtype (Codex, 2026-11-24)

Jen audit. Report napiš česky do `_workspace/2026-11-24_codex_rereview_stonkfly_a_pin_dtype.md`.
Verdikt APPROVE / CHANGES_REQUIRED pro uzavření **statické části fáze A** (A2 zůstává otevřené).

Navazuje na tvůj `_workspace/2026-11-24_codex_rereview_r5_and_stonkfly_a.md`. R5 jsi schválil
(jen kód; nasazení ani `ALLOW_OPEN_POSITIONS=1` se neprovádí), zde jde jen o nález k pinu.

## Změna (lokální, necommitnutá)

`scripts/research/stonkfly_input_sensitivity.py`, `load_receptors()`:
- `PINNED_DTYPES = {"uv": "<f4", "retina": "<i4"}`, tedy stejné typy, jaké vyžaduje živá kontrola
  hlavičky grafu v `src/services/stonkfly/artifacts.py` (`dtypes` u `graph_dtype_mismatch`).
- `verified` je True jen při shodě obou dtype **a** obou hashů bajtů.
- Tvar: `retina.ndim == 1`, `uv.shape == (len(retina), 2)`, jinak `ValueError`. Při pevném dtype a
  tvaru určují bajty v pořadí C jednoznačně hodnoty.
- Docstring popisuje, proč samotný hash bajtů nestačí.

`tests/test_stonkfly_input_sensitivity.py`, `test_pin_check_refuses_same_bytes_under_another_dtype`:
- tvůj scénář `uv.view(">f4")` (stejné bajty, jiné souřadnice) → `verified False`;
- `retina.view(">i4")` → False;
- správné `<f4`/`<i4` → True;
- `<f8` s vlastním odpovídajícím hashem → False;
- `main()` s přehozenou hlavičkou → rc 2, `REFUSED`;
- dvourozměrné `retina` → `ValueError`.

## Důkazy

- Tvůj `_workspace/2026-11-24_stonkfly_pin_header_repro.py` teď vypíše `verified False`
  (`coordinates_identical False`).
- Mutace (kontrola dtype odstraněna, kopie ve scratchpadu) → nový test selže.
- Předepsaná sada: 266 passed, 1 skipped, `PROTECTED_SAME`.
- Server: třetí běh jen pro čtení (skript přes stdin, `nice`/`ionice`, nic nezapsáno) →
  `data_status: VERIFIED_PIN`, `uv_sha256 51f7dafd…`, `frames` identické s prvním během
  (`_workspace/stonkfly_eval_20261123/input_sensitivity_20261124_dtype.json`).
- Report `_workspace/2026-11-24_claude_stonkfly_learning_rework.md` doplněn. `src/services/stonkfly/`
  beze změny, Stonkfly běží.

**Ověřit:** Stačí dtype + tvar + hash bajtů k tomu, aby `VERIFIED_PIN` znamenalo shodné souřadnice?
Je statická část fáze A uzavřená?

Bez SSH, nasazení a commitu. Testy jen
`python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py tests/test_stonkfly_input_sensitivity.py tests/test_stonkfly_integration.py tests/test_paper_neural_context.py`
s kontrolou `protected_sha.py` před a po.
