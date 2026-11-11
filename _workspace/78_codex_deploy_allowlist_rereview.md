# Re-review deploy allowlistu — 2026-11-11

**Rozsah:** nezávislá revize opravy z commitu `e39a1b7` podle `docs/codex_prompts/CODEX_REREVIEW_DEPLOY_ALLOWLIST_2026-11-11.md`; aktuální `HEAD` při review `633f0752a30306e51f43f82bcce4791f7e5676c1`. Claude napsal kontrolovaný skript, já jsem dříve našel P1–P3. Opravu svíček zde znovu nereviduji; její nezávislý report je `_workspace/77_independent_candle_refresh_review.md`. Žádné SSH, nasazení, restart, čtení výsledků C1 ani změna produkčního kódu/testů.

**Verdikt ke skriptu: CHANGES_REQUIRED. Připravenost nasazení: BLOCKED.** P1 a P2 z review 77 jsou převážně opravené. P3 (připnutí přesně schválených bajtů) má závod mezi kontrolou a instalací; schválená verze se může lišit od nasazené, přesto skript skončí `APPLIED OK`. Samostatně stále platí zákaz deploymentu před ověřeným zmrazením C1.

## Blokující nález

**R1 / P1 — závod v `EXPECTED_SHA256`.** `deploy/research_eval/deploy_bot_files.sh:44-51` porovná hash každého souboru v `/tmp/$LABEL` se schválenou hodnotou. Následně do stage kopíruje ze stejného zdroje (`:67-68`) a stage importuje (`:76-96`). Po čekání na nulové pozice (až 60 × 30 s; `:99-105`) instaluje **znovu z měnitelného `/tmp/$LABEL`** (`:138`). Závěrečná kontrola (`:167-168`) porovnává instalaci s jeho *aktuálním* obsahem, nikoli s `EXPECTED_SHA256`. Změna souboru mezi stagingem a instalací tedy projde bez povšimnutí; zvlášť rizikové je `p0_8_plus_live_pipeline.py`, který volá paper executor.

Syntetický důkaz v `_workspace/deploy_allowlist_rereview_20261111/repro_pinned_hash_race.py` zachovává pořadí hash → kopie do stage → vykonání staged modulu → změna zdroje → instalace ze zdroje → porovnání instalace se zdrojem. Výsledek: `postimage_matches_source=true`, `postimage_matches_expected=false`; schválený hash `a8552d1f…`, instalovaný `091609aa…`. Jde o reprodukci logiky na syntetických bajtech, nikoli o spuštění deploye nebo prokázání současné změny souboru na serveru. Dosavadních 22 testů tento scénář nekryje.

**Požadovaná oprava:** instalovat z privátní staged kopie, kterou validoval sandbox, před instalací ověřit její hash proti očekávanému a po instalaci ověřit *instalovaný* hash proti stejné očekávané hodnotě. Stage nenechat smazat před čekáním a instalací; zajistit cleanup i při selhání. Přidat cílený test, který mezi kontrolou a instalací změní původní `/tmp/$LABEL` a dokáže, že se změněné bajty nemohou dostat do běžícího bota. Pouhé opakování hash kontroly zdroje před `install` ponechá kratší závod.

## Ověření původních nálezů a dalších záruk

- **P1, vrstvy konfigurace: opraveno v modelu.** `start.py:9-14` používá `load_dotenv(env_path)` bez `override=True`; aktuální `deploy_env_check.py:85-101` skládá `Environment=` → `EnvironmentFile=` → doplnění `.env`. Plánovaný klíč přítomný v `EnvironmentFile` nebo `.env` odmítá (`:89-92`), hodnotu příznaku kontroluje doslovně `true/false` (`:76-82`). `postcheck()` čte `/proc/<MainPID>/environ` a ověřuje plánované hodnoty (`:104-111`; volání ve skriptu `:163-166`). Syntetické testy pro `.env=false`, `EnvironmentFile=false`, překlep a nesoulad procesu prošly. Tvrzení, že serverový unit nemá `EnvironmentFile=`, pochází od autora/serverového dry runu; kvůli zákazu SSH jsem jej nezávisle neověřil. Repo kopie unit (`deploy/cryptomaster.service:10`) `EnvironmentFile=` obsahuje, proto je správné podporovat i tento případ.
- **P2, staging import: opraveno v kódu.** `deploy_bot_files.sh:76-96` spouští validátory a import každého `FILES` v `systemd-run --wait --pipe`, takže neúspěch by měl pod `set -e` skončit před instalací. [Dokumentace systemd-run](https://www.freedesktop.org/software/systemd/man/256/systemd-run.html) potvrzuje předání standardních streamů pomocí `--pipe` i propagaci návratového kódu při `--wait`. [Dokumentace systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec) říká, že `ProtectSystem=strict` běžně chrání `/opt` před zápisem a `ReadWritePaths` otevírá stage. Nejde o úplnou bezpečnostní izolaci vůči záměrně škodlivému root kódu: `/dev`, `/proc`, `/sys`, mount propagation a privilegované remounty mají v dokumentaci výjimky. Serverový dry run s importem obou modulů a odmítnutím `True` je **převzaté tvrzení**, ne moje reprodukce. Test zápisu na chráněný runtime soubor v sandboxu jsem nespustil; dle zadání žádné SSH.
- **P3, rozšíření allowlistu: názvy a komentář opraveny.** `ALLOWED_FILES`/`ALLOWED_KEYS` (`deploy_bot_files.sh:35-36`) zůstaly na přesně očekávaných čtyřech souborech a povolených klíčích; komentář (`:31-34`) už správně uvádí, že cesta neomezuje chování. Hash je povinný pro každý soubor před zálohou (`:44-51`), ale záruka přesných bajtů končí na R1.
- **Rollback, zámek a drop-in:** zámek před kontrolami (`:28-29`), pořadí drop-inu (`:53-58`) a smyčky zálohy/obnovy/postimage (`:61-63`, `:111-120`, `:167-168`) nebyly změnou odstraněny. Selhání postchecku vyvolá rollback (`:165-166`). Oba nové soubory jsou zahrnuty, pokud jsou v `FILES`. Samotný `deploy_bot_files.sh` a nový `deploy_env_check.py` do tohoto rollbacku nepatří; jejich přenos musí mít vlastní zálohu a hash. Chybějící helper skončí před zásahem (`:16-17`). Runtime rollback na serveru jsem neověřil.
- **LF/CRLF:** pracovní `deploy_bot_files.sh` má 172 LF a 0 CRLF; lokální `bash -n` prošlo. Před serverovou instalací zkontrolovat přesné přenesené bajty, shebang/LF a `bash -n` na staged kopii; lokální výsledek není důkaz serverového přenosu.
- **R2 / P2, parser `EnvironmentFiles`:** `deploy_env_check.py:29,50-55` přijme smíšený řetězec `a.env (ignore_errors=no) GARBAGE` a ignoruje jeho nerozpoznaný konec. Synteticky reprodukováno voláním `env_files()`. Na serveru s prázdným `EnvironmentFiles` bez dopadu; pro obecnou podporu `EnvironmentFile=` má parser odmítnout jakýkoli nerozparsovaný zbytek. Tento nález není důvodem blokace aktuálního běhu s prázdným výpisem, ale před tvrzením o plné podpoře obou případů jej opravit.

## Provedené kontroly

| Kontrola | Výsledek |
|---|---|
| `pytest -q -p no:cacheprovider tests/test_deploy_env_check.py tests/test_deploy_bot_files_allowlist.py` | **22 PASS** |
| AST s gramatikou Pythonu 3.12: helper a oba testy | **PASS** |
| `bash -n deploy/research_eval/deploy_bot_files.sh` | **PASS** |
| Syntetická reprodukce R1 | **PASS** — odhalila instalaci jiného hashe |
| Syntetický neúplný `EnvironmentFiles` výpis | **PASS** — parser ignoroval zbytek |
| Šest chráněných runtime SHA-256 před/po | **SHODA**, hodnoty v `_workspace/deploy_allowlist_rereview_20261111/runtime_sha256.json` |
| Skutečný systemd sandbox, restart/rollback, serverový unit a C1 | **NOT_RUN / NOT_VERIFIED** v tomto review |

Zdrojové soubory a testy byly při review vůči `HEAD` čisté. Přibyl jen tento report a izolované důkazy v `_workspace/`. Žádný závěr o efektu opravy svíček na P/L nebo učení z tohoto review neplyne.
