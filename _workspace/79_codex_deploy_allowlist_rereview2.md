# Druhé re-review deploy allowlistu — 2026-11-11

**Verdikt ke kódu: CHANGES_REQUIRED. Připravenost nasazení: BLOCKED.** V commitu `35881807632dfe853795b8a52c6dcee8abdb63b9` jsou R1 a R2 z review 78 opravené. Závěrečná kontrola však odhalila novou mezeru v importu staged zdroje (N1 níže). Serverový deployment, skutečný restart a rollback jsem podle zadání neprováděl. I po opravě N1 zůstává nasazení blokované do ověřeného zmrazení C1.

## R1 — schválené bajty od stage po postimage

- `deploy/research_eval/deploy_bot_files.sh:17-23,42-50` vyžaduje `EXPECTED_SHA256`, načte obě pomocné knihovny a dovolí jen přesně uvedené cesty a klíče. Zdroj `/tmp/$LABEL` předá pouze `stage_files` (`:55-57`); později jej skript znovu nečte.
- `deploy/research_eval/deploy_pinned.sh:15-21` ukládá každý soubor do privátní stage v režimu 600; rodič stage je 700 (`deploy_bot_files.sh:53`). Hash stage se ověří před zálohou a před jakoukoli změnou bota (`:56-57`). Staging strom pro import vzniká z těchto připnutých souborů (`:73-75`).
- `systemd-run` má `ProtectSystem=strict` a jako zapisovatelnou cestu pouze oddělený `$SCRATCH` (`deploy_bot_files.sh:83-87`), takže běžný zápis z importu do stage ani do `/opt/cryptomaster` nemá projít. Stage se před instalací ověří znovu; instalace čte výhradně stage; nainstalované bajty se ihned i po restartu porovnají **přímo s `EXPECTED_SHA256`** (`:144-146,175`). V tomto běžném modelu je závod ze review 78 uzavřen.
- Vlastní syntetická reprodukce `_workspace/deploy_allowlist_rereview2_20261111/repro_r1_fixed.py` spustila aktuální shell helpery. Po změně původního zdroje zůstala instalace na schváleném SHA-256 `16c6575e63e30ef065e606710a84ffef0d4cddf0893b542aaeb8092dde487d6c`; změna stage byla před další instalací odmítnuta. Výstup: `changed_source_not_installed=true`, `tampered_stage_refused=true`. Není to simulace celého serverového deploye.

## R2 — parser `EnvironmentFiles`

`deploy/research_eval/deploy_env_check.py:29,50-56` nyní ověřuje, že po odebrání rozpoznaných položek nezbyl žádný neprázdný text. Vlastní syntetický vstup `... (ignore_errors=yes) GARBAGE` byl odmítnut, dva korektní záznamy byly načteny. Dřívější model pořadí `Environment=` → `EnvironmentFile=` → `load_dotenv(override=False)` i následná kontrola `/proc/<MainPID>/environ` zůstaly beze změny; `start.py:9-14` skutečně volá `load_dotenv()` bez přepsání existujících hodnot. Tvrzení, že konkrétní serverový unit nemá `EnvironmentFile=`, je převzato z autorova dry runu a v tomto review nebylo nezávisle ověřeno.

## N1 / P1 — staged import může použít starý bytecode

`deploy_bot_files.sh:73-75` kopíruje celé `/opt/cryptomaster/src` do validačního stromu včetně případných `__pycache__`, potom překryje nové `.py` soubory. Původní samostatná kontrola syntaxe `py_compile` už ve skriptu není. `python3 -B -` na řádku `:86` zakazuje **zápis** `.pyc`, nikoli jeho čtení. Import na `:100` proto za určitých okolností může vykonat starý bytecode místo připnutého `.py`: timestamp cache při stejné sekundě změny a stejné velikosti, nebo `UNCHECKED_HASH` cache bez kontroly zdroje. To potvrzuje [dokumentace Pythonu k `-B`](https://docs.python.org/3/using/cmdline.html) a [invalidačním režimům `.pyc`](https://docs.python.org/3/library/py_compile.html).

Vlastní izolovaná reprodukce `_workspace/deploy_allowlist_rereview2_20261111/repro_stale_pyc.py`: staged zdroj vrací `new`, ale import `python -B` v obou uvedených režimech vrátil `old`. Kód tedy může projít preflightem, aniž by se importoval připnutý zdroj. Neprokázal jsem, že přesně taková cache je nyní na serveru; lokální `__pycache__` pro oba moduly existuje a má timestamp režim. N1 je blocker kvůli falešnému důkazu staging importu a možnému restartu s neověřeným kódem.

**Požadovaná oprava:** v preflightu explicitně parsovat/kompilovat přesné `.py` bajty z `$PINNED` bez čtení cache; pro import odstranit zkopírované `.pyc` pouze v dočasném validačním stromu, případně použít prázdnou oddělenou pycache cestu. Test musí vložit starý `.pyc` a nový zdroj stejné velikosti/mtime i neověřovaný hashový `.pyc` a ověřit, že preflight skutečně vykoná nový zdroj nebo bezpečně odmítne. Nezasahovat do produkční `__pycache__` mimo samostatně připravený deploy krok.

## Zachované záruky a hranice ověření

- Zámek před stagingem (`deploy_bot_files.sh:34-35`), kontrola pořadí drop-inu (`:60-64`), záloha před zásahem (`:66-69`), snapshot nulových otevřených pozic (`:105-111`), rollback a obnova SHA (`:113-142`) i kontrola běžícího PAPER prostředí (`:169-175`) zůstaly zachované. Chybějící `deploy_env_check.py` nebo `deploy_pinned.sh` ukončí skript před zásahem (`:18-22`). Pomocné knihovny a deploy skript samy nejsou kryté tímto rollbackem; jejich přenos vyžaduje vlastní preimage, kontrolu hashů a návratový postup.
- `trap EXIT` uklidí stage a scratch při běžném ukončení i po rollbacku (`deploy_bot_files.sh:54`). Pád před instalací trapu (například selhání druhého `mktemp` nebo `chmod`) může ponechat prázdný dočasný adresář; `SIGKILL` či výpadek stroje také cleanup nespustí. Je to nízké provozní omezení, ne cesta k nasazení neověřených bajtů. Po serverovém běhu zkontrolovat případné osiřelé adresáře.
- [Dokumentace systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec) uvádí výjimky `ProtectSystem=strict` pro API filesystémy a privilegované procesy; sandbox zde hodnotím jako ochranu před běžnými import-time zápisy, nikoli jako bezpečnostní hranici proti záměrně škodlivému root kódu. Autorův serverový dry run uvedl odmítnutý zápis do stage (`Read-only file system`) a stejný PID bota; toto je **převzatý důkaz**, ne můj test. [Dokumentace systemd-run](https://www.freedesktop.org/software/systemd/man/256/systemd-run.html) potvrzuje předání stdin přes `--pipe` a návratový kód při `--wait`.
- Pracovní `deploy_bot_files.sh`, `deploy_pinned.sh` i `deploy_env_check.py` jsou pouze s LF (0 CRLF). Před instalací na server kontrolovat přenesené bajty, shebang/LF a `bash -n` **na serverové staged kopii**. Lokální kontrola nedokazuje vlastnosti budoucího přenosu.

## Ověření a důkazy

| Kontrola | Výsledek |
|---|---|
| `tests/test_deploy_env_check.py`, `tests/test_deploy_bot_files_allowlist.py`, `tests/test_deploy_pinned.py` přes pytest s Git Bash v PATH | **27 PASS, 0 SKIP** |
| Stejný běh bez Git Bash v PATH | 22 PASS, 5 SKIP; nepoužito pro verdikt |
| `bash -n` pro oba shell skripty | **PASS** |
| AST Pythonu 3.12 pro helper a tři testovací soubory | **PASS** |
| Vlastní R1 reprodukce v aktuálním Bashi | **PASS**; schválený hash zůstal instalovaný |
| Vlastní R2 reprodukce | **PASS**; nerozpoznaný zbytek odmítnut |
| Vlastní N1 reprodukce | **PASS**; `python -B` načetl starý `.pyc` přes nový zdroj |
| Šest chráněných runtime souborů z `AGENTS.md` | SHA-256 před/po **shodné** |
| Skutečný serverový import, write canary, restart, rollback | **NOT_RUN** v tomto review |

Lokální SHA-256 souborů pro pozdější srovnání při přenosu: `deploy_bot_files.sh` `43523587b0fd4efc327c0138d74fa3bcdc7b14fa597579e173fa3d5691ed7bd4`, `deploy_env_check.py` `ec7f8dd3f4241f86fdcedb58011a7566edf161e3ebd96dfd5de09e120f99d863`, `deploy_pinned.sh` `a9fc279bc781419e6312a9883389f38face552acf7a9fecb449437d08e994335`. Kontrolované zdrojové soubory a testy byly vůči `HEAD` čisté. Změnil jsem jen tento report a izolovaný reproduktor v `_workspace/`; bez commitu a bez zásahu do C1.

**Deployment gate:** nejprve oprava N1 a nové lokální review; samostatně ověřené zmrazení C1 a nezávislá reference původu podle `docs/OPERATING_STATE.md`. Potom teprve přenos všech tří deploy souborů se zálohou a hash/LF kontrolou a oddělené nasazení opravy svíček s novým markerem kohorty. Zelené testy nejsou důkazem zisku ani automatickým pokynem ke změně nákladů.
