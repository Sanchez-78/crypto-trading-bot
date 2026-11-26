# Re-review předregistrace EVENT screen E1/E2, rev. 3 (Codex, 2026-11-26)

Jen audit, bez běhu screenu a commitu. Report napiš česky do
`_workspace/2026-11-26_codex_rereview_event_screen_protocol_r3.md`.
Verdikt: **APPROVE_TO_RUN / CHANGES_REQUIRED**.

Navazuje na tvůj rev. 2 nález: `manifest.json` se zapisoval před kontrolou úplnosti.

| Soubor | SHA-256 |
|---|---|
| `_workspace/2026-11-26_event_screen_protocol.md` (rev. 3) | `06ddbc3f142c7487c5c298cd7b47c4fd9a58f9c1c41053fe21761ae479ec3bcb` |
| `scripts/research/event_shock_screen.py` | `fca9de04303d88cc21a502302076c39c97dff47bd9362fcbed225fcc58349867` |
| `tests/test_event_shock_screen.py` (11 testů) | `c2b3b8844161e08beddf4fe4538ff9530e719e08af883e7bddfa31454a4ed6ab` |
| `scripts/research/futures_flow_screen.py` (beze změny) | `a393d07682630136efd5c29ed6cd6bafbd0cf9b595b32b5c5fff9b5eb1c1328f` |

## Oprava

- **Pořadí v `run()`:** `check_complete(manifest, end)` teď běží **před** zápisem `manifest.json`.
  Při `NOT_EVALUABLE` se nezapíše nic: ani manifest, ani soubory etap.
- **Protokol:** stejné znění je v protokolu (rev. 3).
- **Test:** `test_run_refuses_an_incomplete_archive_set_before_any_stage` nově ověřuje, že výstupní
  adresář je po odmítnutí prázdný nebo neexistuje.
- **Ostatní:** beze změny proti rev. 2 (nulový bootstrap a role TRAIN jsi potvrdil).

Lokálně: 11 testů prošlo a `PROTECTED_SAME`.

**Ověř hashe nezávisle**, například:
- PowerShell: `Get-FileHash -Algorithm SHA256 <soubor>`;
- nebo `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <soubor>`.

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_event_shock_screen.py`.
