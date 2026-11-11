# Nasazení produceru původu C1 (2026-11-11 09:00 UTC)

Schváleno nezávislým review `_workspace/75_codex_c1_provenance_fix3_review.md` (APPROVE pro
commit `fb2faec`, s podmínkou serverového preflightu). Nasadil Claude. Bot se nerestartoval,
evaluator, kritéria ani data se nezměnily.

## Preflight (body 1–4 review 75)

- 08:59 UTC: žádný běh vyhodnocení, příští 17:47. `prereg_result.json`,
  `prereg_provenance.json` ani `*.tmp` neexistují. Výsledky C1 se nečetly.
- Adresář `/opt/cryptomaster_research` je `root:root 755`, `verdict.log` `644` s jedním
  hardlinkem (ext4). Zapisují do něj jen služby roota: `eval` (`run_eval.sh` se `flock`),
  `alert` (jen `ALERT`) a `funnel` (jen `funnel/`). Jména souborů C1 mimo běh vyhodnocení
  nic nemění. Python 3.12.3.
- Na serveru byly SHA verzí před nasazením `7362a118…` (producer) a `34d99f2d…`
  (`run_eval.sh`); evaluator `2b7cbeb7…` se shodoval s lokální verzí.
- Syntetický preflight `deploy/research_eval/preflight_c1_provenance.py` v kopii kódu se
  schváleným producerem, v pracovním adresáři na stejném filesystému: **vše PASS**
  (`c1_provenance_deploy_20261111/preflight_result.json`). Symlink logu na výsledek a
  hardlinky na `prereg_result.json.tmp`, `prereg_provenance.json.tmp` a
  `prereg_provenance.json` byly odmítnuty před zápisem a log zůstal beze změny. Běžné
  zmrazení přes CLI s argumenty z `run_eval.sh` dalo jednu referenci, konzistentní hashe,
  práva 0444 a funkční `fsync` adresáře. Pád před referencí i před výsledkem skončil po
  opakování konzistentní trojicí (u druhého případu nejnovější ze dvou řádek odpovídá
  souborům). `py_compile` (3.12) i `bash -n` prošly. Staging adresář byl poté smazán.

## Nasazení

Pod zámkem `.run.lock` (stejným, jaký používá `run_eval.sh`) jsem vytvořil zálohu
`stage_backups/c1-provenance-20261111T090057Z/` (`SHA256SUMS.before`) a nainstaloval soubory:

| Soubor | SHA po nasazení |
|---|---|
| `code/scripts/research/learner_replay_report.py` | `58b6f8de699106b6cbb0dc090f3ada6a1e44d66654f39df32c4d0636a84e2aee` (= `fb2faec`) |
| `run_eval.sh` | `515090bd76ae75a842b089d8fef112e84215942ec6515bcab69382e3a6851904` (= `fb2faec`) |
| `code/src/services/learner_replay.py` | `2b7cbeb7…117c` (beze změny) |

Ověření: ruční start `cryptomaster-research-eval.service` v 09:01 UTC dal `STATUS OK`. REPLAY
ukázal `prereg=PENDING fresh_n=445/1000 days=2.06/7`, řádka `PROVENANCE` nevznikla (0 v logu),
artefakty C1 ani `ALERT` neexistují a `cryptomaster` je active.

**Rollback:** `install` obou souborů ze zálohy výše.

## Co dál

- První možné zmrazení: běh 2026-11-16 17:47 UTC (7 dní od cutoffu 07:31:56, ≥ 1 000
  obchodů, ≥ 16 bloků a 6 h od posledního hodnoceného vstupu).
- Po zmrazení: najít ve `verdict.log` řádku `PROVENANCE`, ověřit, že oba hashe odpovídají
  existujícímu `prereg_result.json` a `prereg_provenance.json`, a teprve pak ji přenést do
  `docs/OPERATING_STATE.md` (commit a push) jako důvěryhodnou referenci.
- NOT_VERIFIED: skutečný výpadek hosta (fsync je ověřen jen funkčně) a souběh s cizím
  zapisujícím procesem. Na serveru takový proces není, jen root služby.
