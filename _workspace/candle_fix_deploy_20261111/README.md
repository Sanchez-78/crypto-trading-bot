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
