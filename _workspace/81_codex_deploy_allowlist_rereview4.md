# Čtvrté re-review deploy allowlistu — 2026-11-12

**Verdikt ke kódu: APPROVE. Připravenost nasazení: BLOCKED do ověřeného zmrazení C1.** Revidoval jsem commit `1362696670e0a8156ee6fccbb68c1ddb3d43601b` na větvi `main`. N2 z review 80 je opraveno: ochranné kontroly už nelze vypnout optimalizací Pythonu. V rozsahu zadání jsem nenašel další blocker. Na server jsem se nepřipojoval, nic jsem nenasazoval ani nerestartoval; autorův serverový dry run proto zůstává převzatým, ne nezávislým důkazem.

## Oprava N2

- `deploy/research_eval/deploy_bot_files.sh:84-108` spouští validační heredoc jako `/usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" -` a předává vlastní `PYCACHE_PREFIX`. [Dokumentace Pythonu 3.12](https://docs.python.org/3.12/using/cmdline.html) potvrzuje, že `-I` ignoruje `PYTHON*` proměnné prostředí; `-X` určí cache prefix příkazovým řádkem. V heredocu se explicitně volá `verify_staged_import` a odmítnutí končí `STAGED_IMPORT REFUSED`.
- `deploy/research_eval/deploy_env_check.py:116-141` explicitně odmítá chybějící nebo nesouladný cache prefix, chybějící pin, rozdílné bajty, import z jiné skutečné cesty a existující nebo cizí cache. Přesné načtené bajty se kompilují. AST kontrola potvrdila **0 `assert`** v tomto helperu i ve validačním heredocu; ostatní validace v helperu používají `raise Refused`.
- Vlastní offline reproduktor [`repro_isolated_validator.py`](deploy_allowlist_rereview4_20261112/repro_isolated_validator.py) použil aktuální `build_tree` a aktuální `verify_staged_import`. Připravil starý timestamp `.pyc` i starý `UNCHECKED_HASH` `.pyc`, pak nastavil `PYTHONOPTIMIZE=2`, neplatný `PYTHONHOME`, cizí `PYTHONPATH` a cizí `PYTHONPYCACHEPREFIX`. S `-I -B -X` se v obou případech načetl připnutý zdroj (`sys.flags.optimize=0`, `ignore_environment=1`). Chybný hash, chybějící odpovídající prefix a modul dříve načtený z jiné cesty byly vždy odmítnuty. Reproduktor běžel na lokálním Pythonu 3.14; skutečný serverový Python 3.12 jsem nespouštěl.

## Předchozí nálezy a hranice

- N1 z review 79: `deploy/research_eval/deploy_pinned.sh:34-48` sestaví dočasný strom bez `__pycache__`, `.pyc` a `.pyo`; živé cache se nedotýká. Izolovaná reprodukce ověřila oba dříve nalezené režimy starého bytecode. Nový prefix v `$SCRATCH` se zakládá před validací (`deploy_bot_files.sh:74-88`).
- R1/R2 z review 78: staging připne zdroj před změnou živého bota (`deploy_bot_files.sh:53-57`), instalace čte stage a instalované bajty se kontrolují přímo proti `EXPECTED_SHA256` (`:156-158,187`). Parser `EnvironmentFiles` zůstává fail-closed při nerozpoznaném zbytku (`deploy_env_check.py:50-57`). Zámek, záloha, nulové otevřené pozice, rollback, kontrola běžícího prostředí a PAPER invarianty jsou v tomto commitu beze změny.
- Validační `systemd-run` má `ProtectSystem=strict` a zapisovatelný pouze `$SCRATCH` (`deploy_bot_files.sh:84-88`). Úspěšný serverový dry run s nezměněným PID a odmítnutím chybného hashe uvádí autor; toto review jej přes zákaz SSH neověřovalo. Ani lokální testy nenahrazují kontrolu přenesených bajtů a skutečný serverový rollback.

## Ověření

| Kontrola | Výsledek |
|---|---|
| `tests/test_deploy_env_check.py`, `tests/test_deploy_bot_files_allowlist.py`, `tests/test_deploy_pinned.py` se skutečným Git Bash | **35 PASS, 0 SKIP** |
| Vlastní reproduktor N1/N2 (timestamp + unchecked-hash, `PYTHONOPTIMIZE=2`, chybný hash/prefix/původ) | **PASS** |
| `bash -n` pro `deploy_bot_files.sh` a `deploy_pinned.sh` | **PASS** |
| AST Python 3.12 pro helper, tři cílené testy a reproduktor; kontrola `assert` | **PASS, 0 `assert` ve validační cestě** |
| `git check-attr` a pracovní konce řádků u tří deploy souborů | `text eol=lf`, **0 CRLF** |
| Šest chráněných runtime souborů z `AGENTS.md` | SHA-256 před/po **shodné** |
| Skutečný serverový `systemd-run`, restart, rollback | **NOT_RUN** v tomto review |

Pro kontrolu budoucího přenosu jsou lokální SHA-256: `deploy_bot_files.sh` `5b9193e29561dc9aa19b7b77b668ea586d9d83455b1cd0a15ccbae2b686a1723`, `deploy_pinned.sh` `74a1fec742d4e2f219be234f756fa7038f765a3e71b746123d1cd7bb26c214d5`, `deploy_env_check.py` `c323034858ab78660983696bd1e3fa283ff34ecd6dd71d7791041032c0aafaeb`. Kontrolované zdroje a testy byly vůči HEAD čisté. Z tohoto review vznikl jen tento report a izolovaný reproduktor v `_workspace/`.

**Deployment gate:** až po důvěryhodně zmrazeném C1 podle `docs/OPERATING_STATE.md`; při přenosu ověřit schválené hashe, LF a `bash -n` na serverové staged kopii, zachovat zálohu a návratový postup. Následná oprava svíček musí mít vlastní marker nové kohorty. Schválení kódu není schválením změny C1 před zmrazením ani důkazem trading edge.
