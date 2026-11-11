# Oprava B1–B3 produceru původu C1 (2026-11-11)

Podklad: nezávislé review `_workspace/71_codex_c1_provenance_fix_review.md` (CHANGES_REQUIRED).
Implementoval Claude. Nic nenasazeno, server beze změny.

| Nález | Oprava (`scripts/research/learner_replay_report.py`) | Testy (`tests/test_replay_blinding.py`) | Stav |
|---|---|---|---|
| B1 (P1): log mohl ukazovat na výsledek a zápis výsledku pak přepsal jedinou referenci | `validate_freeze_inputs()` porovná `provenance_log.resolve()` (relativní cesty, symlinky) s `resolve()` výsledku, manifestu a jejich `.tmp` a při shodě skončí chybou. Volá ji knihovna před jakýmkoli zápisem a CLI před evaluací (`parser.error`). | `test_b1_log_aliasing_…` (5 aliasů: výsledek, manifest, oba `.tmp`, relativní cesta; nevznikne výsledek, manifest ani `.tmp`), `test_b1_symlinked_log_alias_rejected` (**na Windows SKIP**, chybí oprávnění na symlink), `test_b1_cli_rejects_alias_before_evaluation` (evaluace se nespustí) | PASS (symlink lokálně NOT_VERIFIED) |
| B2 (P2): run ID mohl vložit falešnou řádku PROVENANCE | `RUN_ID_PATTERN = [A-Za-z0-9][A-Za-z0-9._:-]{0,63}`, kontrola v `validate_freeze_inputs` (knihovna i CLI) | `test_b2_run_id_must_be_one_token` (newline s vloženou řádkou, mezera, tabulátor, prázdné, `-lead`, 65 znaků, `\r`, ne-ASCII; nic se nezapíše), `test_b2_cli_rejects_bad_run_id`, `test_b2_valid_run_ids_accepted` (včetně formátu serveru) | PASS |
| B3 (P2): bez `fsync` manifestu a adresáře | `_write_frozen`: zápis, `flush`, `fsync` obsahu, pak `replace`, `chmod 0444` a `fsync` adresáře (`_fsync_dir`, POSIX; na Windows nelze otevřít adresář). `_append_reference`: `fsync` logu a `fsync` adresáře, pokud log vzniká. | `test_b3_content_synced_before_rename_and_directory_after` (pořadí fsync → replace → dir), `test_b3_new_log_directory_synced` | PASS |

**Záruka po B3:** na Linuxu se systémem souborů, který `fsync` respektuje, platí pořadí
manifest (obsah + adresář) → řádka v logu → výsledek (obsah + adresář). Výpadek hosta po
zápisu markeru tedy nemá zanechat výsledek bez manifestu a reference. Skutečný výpadek
hosta **nebyl simulován (NOT_VERIFIED)**. Je to tvrzení o pořadí a synchronizačních
voláních, ne test hardwaru.

Mimo rozsah zůstává: hardlink nebo stejný soubor přes jiný mount
(`resolve()` je nerozliší). Na serveru jsou cesty pevné z `run_eval.sh` (`$BASE/verdict.log`
vs. `$BASE/prereg_result.json`). K posouzení v dalším review (`os.path.samefile`).

## Ověření

- Tři cílené soubory: **171 PASS, 1 SKIP** (symlink na Windows). Runtime data beze změny.
- Mutace `_workspace/c1_provenance_fix2_20261111/mutations.py` (izolovaná kopie,
  `mutation_results.json`): **12/12 zachyceno**. B1: 5 (kontrola odebrána, `.tmp` a manifest
  nechráněné, bez `resolve`, bez kontroly v CLI), B2: 2 (bez kontroly, příliš široký vzor),
  B3: 3 (bez fsync obsahu, adresáře po rename, adresáře nového logu), regrese A1 a A2: po 1.
- AST Python 3.12: PASS; `bash -n run_eval.sh`: PASS (`run_eval.sh` se v této opravě neměnil).

## Další krok

Nezávislé re-review: `docs/codex_prompts/CODEX_REVIEW_C1_PROVENANCE_FIX2_2026-11-11.md` →
`_workspace/73_…`. Při nasazení doplnit do serverového preflightu syntetickou zkoušku
symlinkového aliasu (musí skončit chybou) a zkoušku běžného zmrazení v dočasném adresáři.
