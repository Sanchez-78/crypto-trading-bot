# Nezávislé review opravy původu C1 — 2026-11-11

Zadání: `docs/codex_prompts/CODEX_REVIEW_C1_PROVENANCE_FIX_2026-11-11.md`.
Předmět: commity `c1fe52c` a `efc3447`; HEAD při review
`ea9cabdd91ff3e83e3218655346af57cdce71ab3`, větev `main`.
Toto review provedl Codex, který auditované změny neimplementoval.

## Verdikt

**CHANGES_REQUIRED před nasazením.** Oprava A1 funguje pro konkrétní volání ze
`run_eval.sh`: řádek reference se zapíše a `fsync` proběhne před atomickým zveřejněním
výsledku. A2 je také účinná: běh se souborem `--prereg-result` vyžaduje run ID i cestu
k logu, běžný režim bez tohoto souboru zůstává funkční. Zůstala však reprodukovaná
varianta ztráty reference při platném ručním volání knihovny/CLI (B1). Dále je možné
vložit zdánlivě druhou referenční řádku přes run ID (B2). Obě vady se týkají
produceru, ne evaluatoru či obchodního bota.

| Bod zadání | Výsledek |
|---|---|
| Evaluator, populace, kritéria | PASS pro přesný diff: `src/services/learner_replay.py` se nezměnil; producent pouze uloží jeden `now_ms` a předá jej původní funkci. Hash původní serverové verze produceru podle dokumentace odpovídá lokálnímu parentu. |
| Slepota C1 | PASS v syntetických větvích: PENDING/INSUFFICIENT_DATA se nezmrazí; čerstvé výsledky nečtu. |
| A1, obvyklý běh a pozdější chyby | PASS pro simulované výjimky procesu: log obsahuje reference dříve než zmrazený výsledek; chyba pozdějšího výstupu řádku nesmaže. |
| A1, všechny podporované vstupy | FAIL (B1): při aliasu cesty logu a výsledku existuje zmrazený výsledek bez řádky reference. |
| A2, CLI a knihovna | PASS pro chybějící argumenty při prvním finálním zmrazení. Chybějící argumenty v CLI znamenají chybu ještě před PENDING; `run_eval.sh` je předává vždy, když používá `--prereg-result`. |
| Kompatibilita konzumenta | PASS: cílený end-to-end test vytvoří skutečný syntetický výstup evaluatoru s 2 000 replikacemi a ověří jej existujícím cost review. |
| Plán nasazení | Podmíněně použitelný až po opravě B1/B2 a novém review. Před prvním skutečným zmrazením ověřit absenci obou C1 artefaktů a porovnat log, manifest i result hash; viz níže. |

## B1 — P1: výsledek může přepsat vlastní jedinou referenci

`scripts/research/learner_replay_report.py:125-157` kontroluje pouze neprázdnost
`run_id` a nenulovou cestu `provenance_log`. `main()` (`:176`) kontroluje jen přítomnost
CLI argumentu. Neověřuje se oddělení této cesty od `prereg_result.json` a
`prereg_provenance.json`.

Nezávislý syntetický příklad zavolal veřejnou knihovní funkci s:

```text
path = <tmp>/prereg_result.json
provenance_log = <tmp>/prereg_result.json
run_id = SAME_PATH
```

Funkce vrátila úspěch a hash manifestu; výsledek existuje a je validní JSON.
Zápis výsledku však atomicky nahradil soubor, do kterého se předtím zapsala jediná
`PROVENANCE` řádka. V této cestě tedy po dokončení není žádná reference. Reprodukce
`c1_provenance_fix_review_20261111/reproductions.json`:

```json
"log_aliased_to_result": {
  "result_exists": true,
  "logged_reference_lines": 0,
  "result_is_json": "CONTRARIAN_NOT_SHOWN"
}
```

`run_eval.sh:46` předává při standardním běhu odlišné pevné cesty, takže tento
konkrétní alias na zdokumentované serverové cestě nevzniká. Knihovna a CLI jej přesto
přijímají a končí úspěchem; důsledek je přesně jednorázová ztráta nezávislé reference.

Minimální oprava: před jakýmkoli zápisem odmítnout `provenance_log`, jehož vyřešená
cesta je stejná jako cesta výsledku nebo manifestu, včetně relativních cest a symlinků.
Zachovat fail-closed chování pro první finální zmrazení; regresní testy pro oba aliasy
na úrovni knihovny a CLI. Syntetický test v logu musí ověřit nepřítomnost markeru
výsledku po odmítnutí. Do serverového shell skriptu kvůli tomu není nutné zasahovat.

## B2 — P2: `run_id` může přidat falešnou referenční řádku

`learner_replay_report.py:120` vkládá `run_id` přímo do řádku logu a `:141` kontroluje
jen jeho neprázdnost. Syntetické `run_id` s novým řádkem a druhou řádkou ve formátu
`PROVENANCE` vytvořilo v logu **dvě zdánlivě kompletní reference z jednoho volání**.
Při běžném `run_eval.sh:19` vzniká run ID z UTC data a je bezpečné. Ruční CLI a
knihovní cesta však přijímají neplatné ID. Minimální oprava: omezit run ID na jeden
logový token bez whitespace a řídicích znaků, kontrolovat v knihovně před zápisy;
CLI může odmítnout chybný argument ještě dříve. Testovat newline i tabulátor.

## B3 — P2, omezení tvrzení o odolnosti při výpadku hosta

`learner_replay_report.py:109-113` používá `tmp.write_bytes()`, `replace()` a `chmod()`
bez `fsync` dočasného souboru i rodičovského adresáře. `_append_reference()` volá
`fsync` logu. To prokazuje pořadí v procesu a trvalost appendu do **existujícího**
log souboru po úspěšném systémovém volání; negarantuje však, že manifest a jeho
rename přežijí náhlý výpadek hosta. Při ztrátě manifestu by samotný hash v logu a
existující výsledek nemusely stačit k obnově `evaluated_at_ms` z doby zmrazení.

Výpadek hosta jsem nesimuloval; zdejší poznatek je z pořadí zápisů a chybějících
synchronizačních volání. Buď vymezit záruku jen na selhání procesu a následnou
nezávislou kopii manifestu/reference, nebo doplnit synchronizaci obsahu manifestu a
adresáře před zveřejněním výsledku. Pro tvrzení „crash-safe“ bez rozlišení typu pádu
je toto zatím **NOT_VERIFIED**. Neoznačuji to za prokázanou ztrátu v aktuálním běhu.

## Ověřené chování pádu a opakování

V nezávislém syntetickém reproduktoru jsem nahradil evaluator deterministickým
výsledkem bez tržních dat a vložil chybu ve třech bodech:

| Bod chyby | Stav před opakováním | Druhý běh |
|---|---|---|
| Před zápisem manifestu | Žádný výsledek, žádná reference | Zapíše manifest, referenci a výsledek |
| Před appendem reference | Osiřelý manifest, žádná reference | Přepíše manifest a zapíše referenci i výsledek |
| Před zápisem výsledku | Osiřelý manifest a jedna reference, žádný výsledek | Zapíše nový manifest, druhou referenci a výsledek |

Poslední případ lze rozlišit porovnáním `run_id`, `manifest_sha256` a
`result_sha256` s finálně existujícími soubory. Novější řádka samotná nestačí jako
důkaz: při přenosu do `OPERATING_STATE.md` se musejí porovnat **oba** hashe s
odpovídajícími soubory. Na Windows byl v dočasné syntetické složce původní manifest
před druhým `replace` odemčen; Windows nepovoluje rename přes readonly cíl.
Server je Linux, kde přejmenování přes readonly soubor povoluje zapisovatelný adresář.
Tuto konkrétní serverovou sémantiku jsem bez SSH nezávisle neověřil.

## Testy, diff a integrita

- Porovnal jsem změny od rodiče `c1fe52c` po `efc3447`: změnily se jen
  `learner_replay_report.py` a `run_eval.sh` na relevantní cestě; evaluator ne.
- SHA rodičovského produceru je
  `7362a118c99368114c7c5b841a57fc8e81305f25fb9a83ff74a93116807c877f`,
  shodná s hodnotou uváděnou v provozní dokumentaci jako serverová. Server jsem
  nepřipojil, skutečnou serverovou verzi proto neověřil.
- Lokální `src/services/learner_replay.py` má SHA
  `2b7cbeb76ed868ccb9664bbc03c0a755d2d7f50ede2228a77552b4925699117c`,
  odpovídající dokumentovanému předdeploy kontrolnímu hashi.
- `rtk python -B _workspace/code_audit_20260921_runner.py
  tests/test_replay_blinding.py tests/test_learner_replay.py
  tests/test_cost_and_learning_review.py -q --tb=short`: **151 PASS**, 156,81 s,
  izolovaná kopie; XML `_workspace/code_audit_20260921_ksljgyfh_results.xml`.
- Dosavadní soubor `fix_mutation_results.json` uvádí 11 zachycených mutací.
  Zkontroloval jsem jej, ale mutace jsem v tomto review znovu nespouštěl.
- `bash -n deploy/research_eval/run_eval.sh`: PASS po spuštění Git Bash mimo
  omezení Windows sandboxu. AST syntaxe čtyř dotčených Python souborů pro 3.12:
  PASS. První pokus o testovací snapshot i Git Bash byl omezen sandboxem; cílené
  testy a syntaxe po opakování dokončeny.
- Vlastní syntetická reprodukce:
  `_workspace/c1_provenance_fix_review_20261111/reproduce.py` a
  `reproductions.json`. Žádná skutečná C1 data nebyla otevřena.
- Šest chráněných runtime souborů mělo stejné SHA před/po review. Dva runtime
  SQLite soubory byly již na začátku označené jako změněné vůči Gitu; během review
  se jejich obsah nezměnil. Přesné hashe jsou v `sha_before.json` a `sha_after.json`.

## Bezpečný navazující postup

Claude může malým lokálním patchem doplnit odmítnutí aliasů cest a validaci run ID,
upravit testy a znovu předložit přesný diff k nezávislému review. Vymezení záruky
pro výpadek hosta musí být v reportu i nasazovacím plánu explicitní; pokud má být
garantována i při něm, je potřeba doplnit synchronizaci manifestu a adresáře.

Před případným nasazením stále platí preflight z reportu 70: ověřit nepřítomnost
skutečných `prereg_result.json` a `prereg_provenance.json`, nekolidovat s časovačem,
záloha obou měněných souborů, syntaxe a syntetická zkouška na serveru ve vlastním
dočasném prostoru, kontrola hashů a rollback. `cryptomaster.service` se nerestartuje.
Po skutečném zmrazení přenést do Gitu jen řádku, jejíž oba hashe odpovídají
výsledku a manifestu; nikdy nevytvořit referenci zpětným hashováním neověřeného
artefaktu.

Žádné SSH, deploy, restart, commit, push, reset ani čtení skutečných post-cutoff
outcomes. Kód produceru, evaluatoru a testů jsem neměnil. Nové jsou jen důkazy
v `_workspace/c1_provenance_fix_review_20261111/` a tento report.
