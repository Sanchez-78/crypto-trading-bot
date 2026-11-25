# Review výsledku Stonkfly A2 (Codex, 2026-11-25)

Jen audit, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-25_codex_review_stonkfly_a2_result.md`.

Verdikt pro každý bod:
- **A:** platnost běhu. ACCEPT_MEASURED / REJECT_RUN.
- **B:** výklad. APPROVE / CHANGES_REQUIRED.
- **C:** doporučený další krok Stonkfly.

## Vstupy (lokální, necommitnuté soubory v pracovním stromu)

- Report: `_workspace/2026-11-25_stonkfly_a2_result.md`.
- Výsledek: `_workspace/stonkfly_eval_20261123/a2_result_20261125.json` (sha256 `42151caa…`),
  `MEASURED`, kombinovaný verdikt `INPUT_REACHES_DECODER`.
- Neplatný první pokus: `a2_result_20261125_attempt1_partial.json` (`PARTIAL`, 9× `RuntimeError`
  při startu workeru).
- Smoke: `a2_smoke_20261125.json`. Log: `a2_run_log_20261125.txt`. Spouštěcí skript:
  `a2_setup_20261125.sh` (sha256 `36048e1e…`).
- Protokol: `scripts/research/stonkfly_a2_network_controls.py` (beze změny od tvého APPROVE
  `_workspace/2026-11-24_codex_rereview_stonkfly_a2_r1_r3.md`).
- Kód Stonkfly z produkce: `/opt/cryptomaster/src/services/stonkfly/` (lokálně v
  `C:\Projects\_stonkfly_a2_bundle\prod_readonly.tar`). Relevantní místa:
  - `runtime.py:75–82`: `RLIMIT_AS`;
  - `backend.py:64–66`: dekodér;
  - `config.py:77`: `decoder_threshold_hz` = 2.0.

## A. Platnost běhu

Mezi pokusy 1 a 2 se změnilo **jen prostředí procesu**: `MALLOC_ARENA_MAX=2 ARROW_IO_THREADS=1
LANG=en_US.UTF-8`.
- Hodnoty jsou přečtené z `/proc/<živý worker>/environ` na produkci.
- Bez nich worker na 4 vCPU vrátil `('error','MemoryError')`, protože překročil vlastní
  `RLIMIT_AS` 2 GiB. Produkční VmPeak je 2 025 756 kB.
- Mezi pokusy proběhl jeden diagnostický start workeru (`ready`), bez inference a bez výsledkových
  dat.
- Protokol, snímky a prahy jsou stejné.

**Ověř:** Je pokus 2 platný jediný běh podle schváleného protokolu? Nebo je opakování po
infrastrukturní chybě (pokus 1 bez jakékoli inference) „druhý běh“, který pravidla zakazují?

## B. Výklad

Tvrzení v reportu:
1. **Asymetrie výstupu.** Prázdný snímek má `difference_hz` +14 až +18 Hz (right ~22–28,
   left 6–10).
   - Grafy mění hlavně `left_hz`.
   - Dekodér dá BUY při diff > 0 (HOLD jen při |diff| < 2 Hz). Ani hustá kontrola (30 % pokrytí
     R1–R6) nesníží diff pod 6 Hz.
   - Report z toho vyvozuje, že konstantní BUY vysvětluje **strukturní asymetrie right > left**,
     ne jen slabý vstup.
   - Je to kandidátní mechanismus v baseline stavu (čerstvý checkpoint), ne živý plastic stav.
2. **Tiché KC.** `KC_spikes` = 0 a `changed_edges` = 0 všude, takže plastic = frozen bit po bitu.
3. **Determinismus.** Rozdíly mezi opakováními jsou vývoj stavu, ne náhodný šum: `blank` = `flat`
   přesně.

**Ověř:**
- Vyplývá to z dat?
- Je správné, že verdikt `INPUT_REACHES_DECODER` (podle předem daného pravidla) koexistuje se
  vstupem WEAK? Report ho nepřeformulovává ani neladí prahy.
- Je `falling` (12 Hz proti pásmu [13; 19] ± 1) na hraně pravidla? Pravidlo se nemění, jde jen
  o výklad síly efektu.

## C. Další krok

Návrhy, nic neimplementováno. Každý vyžaduje vlastní protokol a plán verzování checkpointu, protože
`src/services/stonkfly/` se nesmí měnit bez něj:
1. dekódovat změnu proti baseline (diff − diff prázdného snímku);
2. symetrický vstup do obou polovin zorného pole;
3. diagnostika tichých KC.

Seřaď je, nebo navrhni jiný postup. Stonkfly se nevypíná, dál běží jako shadow (`observation_only`).

Testy: `PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_stonkfly_a2_network_controls.py`.
