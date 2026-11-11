# Audit produceru manifestu původu C1 (2026-11-11)

> **Dodatek: oprava A1/A2 (2026-11-11, Claude, na pokyn operátora).**
> - **A1:** `learner_replay_report.py` při zmrazení zapíše manifest, hned potom připíše do
>   `--provenance-log` (na serveru `verdict.log`, předává `run_eval.sh`) řádku
>   `PROVENANCE run=… manifest_sha256=… result_sha256=…` s `fsync` a teprve pak zapíše
>   výsledek, tedy marker zmrazení. Pokud výsledek existuje, jeho reference už je v logu
>   a selhání pozdějších kroků běhu ji neztratí.
> - **A2:** `--prereg-result` vyžaduje `--run-id` i `--provenance-log` (chyba argumentů) a
>   knihovní funkce zmrazení bez nich odmítne. Náhradní hodnota `unspecified` je odstraněna.
> - Testy: `tests/test_replay_blinding.py` +6 (řádka jednou a se správnými hashi, přežije
>   selhání po zmrazení, vzniká před markerem, povinnost obou argumentů v CLI i knihovně).
>   Tři cílené soubory: **151 PASS**. Mutace `fix_mutations.py`: **11/11 zachyceno** (A1: 4,
>   A2: 2, dřívější vlastnosti: 5), výsledky v `fix_mutation_results.json`. Runtime data
>   beze změny. `reproduce.py` (A2) je historický: po opravě skončí chybou argumentů, což
>   je očekávané.
> - **Stav:** opraveno autorem. **Nezávislé review opravy dosud chybí.** Bez něj se podle
>   `OPERATING_STATE` nenasazuje.

Zadání: `docs/codex_prompts/CODEX_AUDIT_C1_PROVENANCE_PRODUCER_2026-11-10.md`.
Předmět: commit `c1fe52c90262ddd6d85565271d9e827653e86849` (HEAD v době auditu), diff v
`c1_provenance_audit_20261110/subject.diff`.

> **Upozornění k nezávislosti:** zadání bylo připravené pro Codex jako nezávislého auditora.
> Na pokyn operátora ho provedl Claude, tedy **autor auditované změny**. Audit jsem vedl
> s cílem změnu zamítnout a všechna tvrzení doložil, ale **nejde o nezávislé review**, které
> `docs/OPERATING_STATE.md` vyžaduje před nasazením změny protokolu. Nalezené vady si
> nemůže sám schválit ten, kdo je napsal.

Při auditu nebyl změněn kód ani testy, neproběhl SSH, deploy, commit, restart ani reset a
neotevřela se žádná skutečná post-cutoff data. Používal jsem jen syntetická data.

## Verdikt

**CHANGES_REQUIRED** (jedna vada P1, jedna P3). Evaluator i slepota jsou v pořádku. Vada P1
ale může přesně v okamžiku zmrazení natrvalo ztratit důvěryhodnou referenci, a tím zmařit
účel změny.

## Ověření podle bodů zadání

| Bod | Výsledek | Důkaz |
|---|---|---|
| 1. Evaluator se nemění | **PASS.** Rodičovská verze má SHA `7362a118…877f` (= server). Jediná změna v cestě vyhodnocení je `now_ms = round(time.time() * 1000)` do proměnné, předané stejně do `evaluate_preregistered`. Kritéria, hodnocená množina i verdikt se nemění. | `subject.diff`, `learner_replay_report.py:118-120` |
| 2. Slepota | **PASS.** Producer zapisuje a tiskne jen hash manifestu. PENDING i INSUFFICIENT_DATA nezapíšou nic (testy `test_pending_or_insufficient_writes_no_provenance`, `test_insufficient_data_is_never_frozen`). Nic se nečte navíc. | `learner_replay_report.py:122-136` |
| 3. Vazba | **PASS.** `result_sha256` je hash přesně zapsaných bytů (`payload`) a `evaluated_at_ms` je `now_ms` evaluatoru. Cutoff je z argumentu, který už porovnává `prereg_result_cutoff_mismatch`. Konvence ID se shoduje s konzumentem (end-to-end test přijetí). | `test_freeze_writes_provenance_bound_to_exact_result_bytes`, `test_produced_manifest_is_accepted_by_cost_review` |
| 4. Pořadí, pády, souběh | **FAIL (A1)** + informační A3. Pád mezi zápisy nevadí: osiřelý manifest se při dalším vyhodnocení přepíše (rename na Linuxu nepotřebuje právo zápisu do cílového souboru). Souběh řeší `flock` (`run_eval.sh:17`). | níže |
| 5. Kompatibilita | **PASS.** Existující zmrazený výsledek se vrací beze změny a bez hashe. `--run-id` se předává jen ve větvi s `prereg_after`. Anotace `tuple[dict, str | None]` jsou s `from __future__ import annotations` platné v Pythonu 3.12. Nasazení nepotřebuje restart bota. Poznámka: dřívější `write_text` na Windows zapisoval CRLF, nyní `write_bytes` LF. Na serveru (Linux) jsou byty shodné. | — |
| 6. Testy | **PASS s výhradou.** End-to-end test trvá desítky sekund až minuty, je ale jediný, který ověřuje přijetí skutečného výstupu evaluatoru konzumentem. Doporučuji ho ponechat. | `tests.txt` |
| 7. Plán nasazení | Doplnit podle A1 až A3 (níže). | — |

## Nálezy

### A1 — P1: hash manifestu se může ztratit přesně v běhu, který zmrazil

`run_eval.sh` připisuje řádku REPLAY (s `provenance_sha256=`) do `verdict.log` až na
**řádku 122**. Před ní běží kroky, které mohou selhat a ukončit běh přes `fail()`:
- kohortní report (`:52`), který se spouští **právě v běhu, který zmrazil**, protože
  `prereg_result.json` už existuje;
- manifest běhu (`:69`), souhrn (`:91`) a trap `ERR`;
- i samotný Python po zmrazení (zápis `replay.json`/`replay.md`). Pak `$(…)` selže a
  `fail replay` řádku nezapíše.

Další běhy výsledek jen vracejí a hash už nevypíšou (`frozen_preregistered` vrací
`(frozen, None)`). Synteticky potvrzeno v `reproductions.json` A1: běh, který zmrazil,
hash tiskne, další běh ne. Důsledek: soubory existují, ale nezávislá reference z doby
zmrazení chybí. Dodatečně spočítaný hash by byl odvozený z ověřovaného souboru, takže by
reference nebyla nezávislá.

**Doporučená oprava:** zapsat referenci hned po zmrazení, nezávisle na zbytku běhu.
Například `learner_replay_report.py --provenance-log <verdict.log>` po zápisu obou souborů
okamžitě připíše řádku `PROVENANCE run=<id> manifest_sha256=<…> result_sha256=<…>`
(append + flush/fsync), ještě před zápisem `replay.*`. `run_eval.sh` předá cestu k
`verdict.log`. Stávající tisk na stdout lze ponechat. Přidat testy: řádka vzniká i při
selhání pozdějšího kroku a vzniká jen jednou.

### A2 — P3: zmrazení bez `--run-id` vytvoří `run_id: "unspecified"`, které konzument přijme

`learner_replay_report.py:126` (`run_id or "unspecified"`) a
`cost_and_learning_review.verify_provenance` kontrolují jen neprázdnost. Reprodukce A2.
Server `--run-id` vždy předá, ruční běh by ale vytvořil slabě vázaný manifest.
**Doporučení:** při `--prereg-result` vyžadovat `--run-id` (chyba argumentů, fail-closed)
nebo v konzumentovi odmítnout `unspecified`.

### A3 — informační: `verdict.log` není odolný proti úpravě

Leží na stejném serveru a root ho může přepsat. Je to nejlepší dostupné místo bez nové
služby. Doporučuji, aby agent hned po zmrazení přenesl řádku `PROVENANCE` do gitu (do
`docs/OPERATING_STATE.md`, commit a push) a tím vznikla druhá kopie mimo server. To už
plánuje `OPERATING_STATE`. Volitelně uložit hash i do `manifest.json` daného běhu.

## Doplněný plán nasazení (po opravě A1/A2 a nezávislém review)

1. Ověřit, že `prereg_result.json` ani `prereg_provenance.json` na serveru neexistují a
   neběží vyhodnocení (`.run.lock`). Nasazovat mimo okna 05:47 a 17:47.
2. Zálohovat a zaznamenat SHA `code/scripts/research/learner_replay_report.py` a
   `run_eval.sh`. Ověřit, že `code/src/services/learner_replay.py` má SHA `2b7cbeb7…117c`
   (shodný s lokálním).
3. Kopie, SHA po, `bash -n run_eval.sh`, `python3 -m py_compile` do dočasného adresáře.
4. Syntetická zkouška na serveru v dočasném adresáři: `--json <syntetický export>
   --prereg-result <tmp> --provenance-log <tmp log> --run-id test`. Nikdy nad skutečnou DB
   a nikdy s reálnou cestou k výsledku.
5. Další běh časovače: `STATUS OK`, REPLAY `prereg=PENDING`, žádná řádka PROVENANCE.
6. Po skutečném zmrazení: řádku PROVENANCE zapsat do `OPERATING_STATE` (A3).
7. Rollback: obnovit oba soubory ze zálohy.

## Testy a integrita

- `rtk proxy python -B _workspace/code_audit_20260921_runner.py tests/test_replay_blinding.py tests/test_learner_replay.py tests/test_cost_and_learning_review.py -q --tb=short`
  → **145 PASS** (`tests.txt`).
- Reprodukce: `rtk proxy python -X utf8 -B _workspace/c1_provenance_audit_20261110/reproduce.py`
  → `reproductions.json` (A1, A2).
- SHA šesti chráněných runtime souborů před = po (`sha_before.txt`, `sha_after.txt`).

## Ověřeno vs. předpoklad

Ověřeno: diff, hashe verzí, pořadí kroků v `run_eval.sh`, chování A1 a A2 na syntetických
datech a testy. Předpokládáno a neověřeno na serveru: chování `rename` nad souborem 0444
(standardní sémantika POSIX), verze Pythonu na serveru (3.12 podle `AGENTS.md`) a skutečná
pravděpodobnost selhání kohortního reportu.
