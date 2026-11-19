# Re-review nasazení po C1 a stropu bucketu — 2026-11-19

Rozsah: zadání `docs/codex_prompts/CODEX_REREVIEW_POST_C1_DEPLOY_AND_BUCKET_CAP_2026-11-19.md`. Jen lokální čtení a cílené testy; bez SSH, nasazení, Firebase, commitu a změny runtime dat.

| Část | Verdikt | Důvod |
|---|---|---|
| A — dashboard readiness | **APPROVE nasazovací krok** | Profil, journal, obnova i atributy souborů jsou kontrolované. Skutečný běh na serveru zůstává `NOT_RUN`. |
| B — bot / viditelnost outboxu | **CHANGES_REQUIRED** | Nasazovací skript může přepsat živý soubor, který už neodpovídá schválenému serverovému preimage. |
| C — strop bucketu | **APPROVE kód a artefakt** | Dvouhunkový diff proti ověřené serverové kopii obsahuje jen změnu stropu; parser a rozsah vyhovují. Nasazení stropu tímto verdiktem schválené není. |

## Blokující nález B4 — chybí kontrola živého preimage před přepsáním (P1)

`deploy/research_eval/deploy_bot_files.sh:65–66` připne **nový** zdroj a `:160–162, :193` ověří připnutý zdroj, nainstalovaný soubor a postimage. Nikde před `install_staged` neporovná aktuální `$APP/$f` s `preimage_sha256` z `_workspace/deploy_post_c1_20261119/MANIFEST.json`. `deploy_pinned.sh:24–33` zná jen hash předaný v `EXPECTED_SHA256`, což je v runbooku (`docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md:77–83`) hash **nového** souboru.

Reprodukce z toku kódu: po pořízení serverové kopie se jeden živý outbox modul změní; deploy zazálohuje tuto novou verzi, validuje starý schválený artefakt, `install_staged` novou živou verzi přepíše a oba následné `verify_pinned` projdou. Nejde o hypotetickou chybu v hash funkci, ale o chybějící volání nad živým preimage. Dashboard má naopak kontrolu na řádku `deploy_dashboard_readiness.sh:55`.

Před schválením B předejte skriptu připnuté *staré* hashe obou outbox modulů a pod zámkem odmítněte odlišný `$APP/$f` před prvním zápisem. Kontrolu zopakujte bezprostředně před instalací, protože preflight/import může trvat; doplňte regresní test, kde se živý soubor mezi kontrolou a instalací změní. Nepostačí jen ruční hash před spuštěním skriptu mimo jeho zámek. Runbook má přesné preimage hashe `a3d7d7a4…4413` a `b173ea7c…6e9e`.

## A — dashboard

- `deploy_dashboard_readiness.sh:44–50` živým požadavkem rozliší veřejný profil (200 bez tokenu) od chráněného (401/503 a funkční token). `:104–116` po restartu ověří stejný profil a kontrakt readiness. Veřejný profil token nevyžaduje.
- `/run/credentials/cryptomaster-dashboard.service/dashboard_api_token` je správná cesta k účinné kopii credential systémové služby, včetně dešifrovaného `LoadCredentialEncrypted`; soubor je přístupný uživateli služby a rootovi podle [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html). Token se v `:29–36` předává do curl přes stdin (`-H @-`), bez argumentu procesu nebo logu. Tento způsob podporuje [manuál curl](https://curl.se/docs/manpage.html). Živou konfiguraci systemd jsem v tomto review nečetl (`NOT_VERIFIED`).
- `:126–128` při chybě `journalctl` nebo prázdném journalu volá rollback; `:75–92, :133–136` ověřuje hash, mód, UID a GID při rollbacku i po instalaci. Souborům zachovává původní mód a vlastníka.
- `PINS` odpovídají manifestu. Artefakt `dashboard_web.py` má přesný SHA-256 `df8b50411afdd84e9bee685dc4e3457303a3e94d769dc5b5e1a69c1fb1d1e02e`; nezměněné řádky jsou bajtově identické se serverovou kopií.

## B — bot / outbox

- `deploy_bot_files.sh:47–48` povoluje oba outbox moduly; executor a `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET` nepovoluje. Odložený patch `allowlist_executor_after_approval.patch` vrací přesně tento soubor a klíč, aktualizuje statický test a `git apply --check` prošel. Patch se neaplikoval.
- `:181–183` nyní odmítne chybu čtení i prázdný journal a provede rollback. Záloha vytváří vnořené adresáře a ploché zdrojové adresáře odmítají duplicitní basename.
- Čtyři artefakty readiness/outboxu odpovídají manifestu i zaznamenaným SHA-256 serverových kopií. Všechny nezměněné řádky jsou bajtově shodné. `.gitattributes` u dvou smíšených/CRLF artefaktů vrací `text: unset`; raw blob ID pracovního souboru a commitu `HEAD` jsou shodná. Plošný převod na LF v připnutých artefaktech nenastal.
- `build_artifacts.py:72` porovnává obsah změněných řádků, takže změna textu stejné délky neprojde. Kontrola používá `sorted(d)` a neověřuje polohu hunků: pro `old = "foo\nbar\nfoo\nbaz\n"` mají alternativy s výměnou prvního nebo druhého `foo` za `X` stejný seřazený seznam `['+X', '-foo']`, ačkoli jde o jinou změnu. **P2, neblokující pro aktuální připnuté artefakty**, jejichž diff byl ověřen samostatně a které runbook výslovně zakazuje regenerovat. Formulace „přesně schválený diff“ v runbooku je silnější než skutečná záruka builderu. Při další regeneraci porovnávat plný patch včetně hunků/kontextu.

## C — strop bucketu

- Serverová kopie executoru má SHA-256 `5b0b15cc0ba98632f866267dac462286c07ecce6d8bbaa9a033120b29fa361cc`, artefakt `a39d4f4c3c0d72e3a59a80078be6887ef9f413513b99f5e37d87359e9f406a12`. Vygenerovaný diff jsem nezávisle porovnal s uloženým `server_to_artifact.diff`: bajtově stejný text, 2 hunky, +25/−2. Změny jsou výhradně nový helper stropu, jeho dokumentace a náhrada pevné dvojky v `bucket_count` kontrole. Nezměněné řádky mají identické bajty včetně CRLF/LF; artefakt má stejný Git blob ID v pracovním stromu a `HEAD`.
- `paper_trade_executor.py:1550–1562` rozpoznává přesné hodnoty 1–7 bez konverze uživatelského řetězce na `int`, chybné hodnoty včetně 5000 číslic vrátí na 2. `deploy_env_check.py:83–87` před konverzí omezuje vstup na 1–3 ASCII číslice a odmítne neplatný rozsah. Zvýšení se vztahuje jen na `P0_8_PLUS_EVIDENCE_COLLECTION`, ostatní buckety mají 2. Přijímací i předinsertová kontrola volají stejnou `_check_exploration_exposure_caps()` (`paper_trade_executor.py:1992, :2374`).
- Runbook `:109–110` správně uvádí, že snížení stropu neuzavírá otevřené pozice; pouze blokuje další vstupy, dokud počet neklesne. Doložené mutační výsledky: 4/4 zachycené. Vlastní serverový test ani restart nebyl proveden (`NOT_RUN`).
- `build_artifact.py:40` kontroluje, zda **každý hunk** obsahuje aspoň jednu značku; neodmítne cizí změněný řádek přidaný do téhož hunku. **P2, neblokující pro současný artefakt**, jehož úplný diff je nezávisle zkontrolovaný. Před případnou regenerací vyžadovat přesný očekávaný patch, nikoli jen marker hunku.

## Ověření a limity

- Povolených pět testovacích souborů: **72 PASS, 8 SKIP**. Přeskočené testy v `test_deploy_pinned.py` vyžadují `bash` v `PATH`; lokálně tam nebyl. Oba nasazovací skripty následně prošly `bash -n` přes explicitní Git Bash.
- Pokus zpřístupnit Git Bash testům skončil ještě při importu `tests/conftest.py`: Windows `PermissionError` při `os.chdir()` do nového dočasného adresáře, jednou i pod `_workspace`. Žádný test se v těchto dvou pokusech nespustil. Proto se osmi Bash testům nepřipisuje PASS. Tento neúspěšný běh vytvořil `_workspace/cm_test_local_cache_c89pxmc4`; v aktuálním sandboxu nejde ani otevřít, proto jsem ho nemazal. Kontrolní snapshot je `_workspace/protected_rereview_20261119_pre.json`.
- Nezávisle přepočtené hashe všech pěti serverových kopií a artefaktů souhlasí s manifesty. `protected_sha.py check` před i po testech hlásí `PROTECTED_SAME`. Lokální pracovní strom zůstal záměrně dirty; žádná stávající změna nebyla vrácena ani commitnuta.
- Skutečné serverové preimage, účinný systemd profil, živý journal a behavior po restartu nebyly v tomto zadání ověřovány. Bez opravy B4 nedoporučuji nasadit outbox. Schválení A neznamená provedené nasazení; schválení C neznamená povolení jeho env klíče ani instalaci executoru.
