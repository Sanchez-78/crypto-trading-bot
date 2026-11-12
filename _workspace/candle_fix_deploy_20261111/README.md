# Oprava review 77 (deploy allowlist), 2026-11-11

- P1: `deploy/research_eval/deploy_env_check.py` - efektivni prostredi ve vrstvach jako bezici bot:
  systemd Environment= -> EnvironmentFile= (prepisuje) -> /opt/cryptomaster/.env pres python-dotenv
  (override=False, jen doplnuje). Na serveru overeno: efektivni unit nema EnvironmentFile=, .env nacita
  start.py pres load_dotenv. Planovany klic nesmi byt v EnvironmentFile ani v .env (odmitne i preklep).
  Po restartu se overuje skutecne /proc/<MainPID>/environ (+ .env doplneni pro invarianty).
- P2: validatory a import vsech nasazovanych modulu bezi v `systemd-run -p ProtectSystem=strict`
  se zapisem jen do STAGE_DIR; pokus o zapis runtime dat deploy zastavi pred zasahem do sluzby.
- P3: povinne EXPECTED_SHA256 (presne reviewovane bajty kazdeho souboru), pravdivy komentar.
- Testy: tests/test_deploy_env_check.py (18) + tests/test_deploy_bot_files_allowlist.py (4): 22 PASS
  (spusteno primo pytestem; izolovany runner nekopiruje .py z deploy/). Runtime SHA beze zmeny.
- Mutace deploy_env_check (env_check_mutations.json): 7/7 zachyceno (po doplneni testu poradi drop-inu).
- Server dry run (bez instalace a restartu, PID bota beze zmeny): sandbox preflight se staged opravou
  a VARS flag=true -> config ok, import obou modulu OK v read-only sandboxu; flag=True -> REFUSED.
- Server ma porad starou verzi skriptu (52d50fe7); nova + deploy_env_check.py se nasadi spolu s opravou
  svicek az po zmrazenem C1.

## Oprava review 78 (2026-11-11)

- R1 (zavod v EXPECTED_SHA256): novy `deploy/research_eval/deploy_pinned.sh` (stage_files, verify_pinned,
  install_staged). Zdroj `/tmp/$LABEL` se cte jen jednou do privatniho stage (700) a hash se overi na stage.
  Validacni strom se stavi ze stage; sandbox ma stage jen pro cteni (ReadWritePaths=$SCRATCH). Pred instalaci
  se stage overi znovu, instaluje se ze stage a instalovane bajty se porovnaji primo s EXPECTED_SHA256
  (po instalaci i v postimage). Uklid stage/scratch pres trap EXIT. `$NEW` se ve skriptu cte jen jednou.
- R2: parser EnvironmentFiles odmitne jakykoli nerozparsovany zbytek.
- Testy: test_deploy_pinned.py (5, skutecny bash: podvrzeni zdroje po kontrole se do cile nedostane,
  podvrzeny stage odmitnut, instalace se porovnava s pinem, ne se zdrojem) + env_check (19) + allowlist (4):
  27 PASS, runtime SHA beze zmeny. Mutace r1_mutation_results.json: 6/6 zachyceno.
- Server dry run (bez instalace a restartu, PID 75073 beze zmeny): pin drzi i po zmene zdroje, sandbox
  config ok ze stage, zapis sandboxu do stage -> Read-only file system, stage nezmenen.

## Oprava review 79 (N1, stary bytecode), 2026-11-11

- `build_tree` v `deploy_pinned.sh`: validacni strom = src bota bez `__pycache__`/`*.pyc`/`*.pyo` + pripnute
  soubory; zbyly bytecode -> chyba. Zivy `__pycache__` bota se nemeni.
- Sandbox: prazdny `PYTHONPYCACHEPREFIX` ve scratch (Python pak .pyc vedle zdroju vubec nehleda) a pro kazdy
  nasazovany modul: hash bajtu ve strome == pin, `compile()` presnych bajtu, `module.__file__` == pripnuty zdroj,
  `module.__spec__.cached` jen v prazdnem prefixu a neexistuje (zadna cache nepouzita).
- Testy: +3 (stary .pyc v rezimu timestamp se stejnou velikosti/mtime i unchecked-hash -> importuje se pripnuty
  zdroj; kontrolni test, ze bez ochrany se opravdu importuje stary kod). Celkem 30 PASS, runtime SHA beze zmeny.
  Mutace n1_mutation_results.json: 5/5 zachyceno.
- Server dry run (bez instalace/restartu, PID 75073): zivy src ma 9 adresaru __pycache__ (riziko realne),
  validacni strom 0, sandbox config ok vcetne kontrol identity zdroje, do prefixu 0 .pyc, zivy __pycache__ beze zmeny.

## Oprava review 80 (N2, assert jako bezpecnostni kontrola), 2026-11-12

- Kontroly identity zdroje presunuty z heredocu do `deploy_env_check.verify_staged_import()` s explicitnim
  `Refused` (zadny `assert` ve validatoru ani v `deploy_env_check.py`; overeno AST testem).
- Validacni interpreter bezi `python3 -I -B -X pycache_prefix=...`: `-I` ignoruje vsechny PYTHON* promenne
  (vcetne PYTHONOPTIMIZE); prefix se predava pres -X a funkce odmitne beh bez nej.
- Testy: +5 (pod `-O` i PYTHONOPTIMIZE=2: pripnuty zdroj OK, spatny hash a modul nacteny odjinud odmitnuty,
  chybejici prefix odmitnut; v heredocu ani helperu zadny assert). Celkem 35 PASS. Mutace
  n2_mutation_results.json: 5/5 zachyceno.
- Server dry run (bez instalace/restartu, PID 75073) s podvrzenym PYTHONOPTIMIZE=2 v sandboxu: spravne
  piny -> config ok; spatny hash -> STAGED_IMPORT REFUSED; 0 .pyc v prefixu.
