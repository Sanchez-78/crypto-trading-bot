# Externí audit: vyhodnocování učení PAPER bota a autonomní proces agenta (2026-11-09)

Jsi nezávislý auditor (kvantitativní výzkum + softwarové inženýrství). Audituješ
**vyhodnocování učení** obchodního bota CryptoMaster a **pracovní proces AI agenta**
(Claude Code), který ho od 2. 10. 2026 navrhuje, nasazuje a vyhodnocuje převážně
autonomně. Odpovídej **česky**. Tvým úkolem je najít chyby, ne potvrdit závěry.
Kde nemůžeš něco ověřit, napiš `NOT_VERIFIED` a proč.

## Pravidla

- Pracuj jen čtením repozitáře a evidence. Nic necommituj, nespouštěj SSH, deploy
  ani GitHub workflow, neměň `local_learning_storage/**`, `runtime/**`, `data/**`,
  `server_local_backups/**` ani soubory v `docs/codex_prompts/evidence/`.
- Výpočty si můžeš ověřit vlastními skripty ve vlastní dočasné složce.
- Testy: `python -m pytest -q -p no:cacheprovider <soubor>` (jen cílené soubory níže).
- Bot je **PAPER only** (virtuální peníze). Ztráta sama o sobě není nález;
  operátor 9. 11. výslovně řekl: „imaginární ztráta nevadí, potřebujeme co nejvíce
  obchodů pro proces učení a metriky, proč se učení zlepšuje/nezlepšuje“.

## Kontext v kostce (ověř, nepřebírej)

- Strategie navrhují kandidáty; učení `paper_source_learning_v1` je jen **filtr**:
  odhad = smrštěný EWMA průměr post-cost bps kontextu (source, symbol, regime, side),
  pravděpodobnost vstupu = sigmoid(odhad/10 bps) v [0,1; 0,9]; 20 % kandidátů je
  CONTROL bez filtru. Náklad v paper modelu 9 bps/obchod.
- Epocha od 25. 9.: 915 obchodů, net −8,98 bps/obchod, hrubý pohyb po vstupu
  +0,02 ± 1,34 bps.
- Experiment ADAPTIVE vs CONTROL (n = 355/341): +1,39 bps, CI [−1,42; +4,20] →
  `SELECTION_EFFECT_NOT_SHOWN`.
- Diagnostika předpokladů učení: kontexty se neliší od šumu (χ² p = 0,75), nejsou
  stálé (ρ = −0,19), odhad učení vs výsledek ρ = −0,11, výhoda ADAPTIVE klesá po čtvrtinách.
- Walk-forward replay 10 variant: všechny mají na holdoutu **záporný** lift
  (současné pravidlo −3,50 bps [−7,52; +0,51]). Z toho agent odvodil a
  **předregistroval** protisměrnou hypotézu C1, hodnocenou jen na obchodech po
  `prereg_after = 1794209516` (2026-11-09 07:31:56 UTC).
- Živý stav od 9. 11.: limity průzkumu 480/den, 30/h, cooldown 300 s, min. modelovaný
  net −25 bps, bez blacklistu symbolů, `PAPER_LEARNING_CONTROL_FRACTION=1.0`
  (všichni kandidáti vstupují, odhad se jen loguje).

## Materiály k auditu

**Pravidla a zadání**
- `AGENTS.md`, `CLAUDE.md` (pozor: části jsou historické/zastaralé)
- `docs/codex_prompts/CODEX_STRATEGY_LEARNING_TASKS_2026-10-02.md`
- `docs/codex_prompts/CODEX_LEARNING_EXPERIMENT_EVAL_2026-10-26.md`

**Návrh a průběh učení (chronologicky)**
- `docs/remediation/PAPER_LEARNING_2026-10-19.md`, `_workspace/54_paper_adaptive_learning_20261019.md`
- `docs/remediation/PAPER_PROBES_2026-10-23.md`, `_workspace/56_paper_probes_20261023.md`
- `docs/remediation/STONKFLY_CONTEXT_2026-10-20.md`, `_workspace/55_stonkfly_main_decision_20261021.md`
- `docs/remediation/DECISION_STATUS_2026-10-15.md`, `_workspace/53_decision_status_and_learning_audit_20261016.md`
- `docs/remediation/UNIFIED_ENGINE_2026-10-08.md`

**Vyhodnocení a závěry agenta**
- `_workspace/50_codex_strategy_learning_report.md`
- `_workspace/57_codex_learning_experiment_eval.md`
- `_workspace/58_why_bot_does_not_improve.md`
- `src/services/LOGIC.md` (sekce od „6. P0.8+ evidence budget“ do konce)
- `docs/remediation/AUTONOMOUS_LEARNING_LOOP_2026-10-26.md` (původní pravidla S1→S2→S3 a jejich zrušení)
- `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`
- `_workspace/autonomy/LOOP.md`, `_workspace/autonomy/daily.md`,
  `_workspace/autonomy/2026-11-09_S2.md`, `_workspace/autonomy/state.json`

**Dřívější výzkum**
- `RESEARCH_PIVOT_CHARTER.md`, `RESEARCH_COSTWALL_FINDINGS.md`,
  `RESEARCH_M5_COST_ARITHMETIC.md`, `RESEARCH_LONGHORIZON_FINDINGS.md`,
  `RESEARCH_FUNDING_CARRY_FINDINGS.md`

**Kód měření a učení**
- Živé: `src/services/paper_source_learning.py`, `src/services/paper_learning_budget.py`,
  `src/services/evidence_budget.py`
- Offline: `src/services/learning_experiment_verdict.py`, `src/services/learning_diagnostics.py`,
  `src/services/learner_replay.py`, `scripts/research/p0_8_plus_epoch_report.py`,
  `scripts/research/learner_replay_report.py`
- Provoz: `deploy/research_eval/` (`run_eval.sh`, `apply_stage.sh`, `stage_step.sh`,
  `deploy_bot_files.sh`, `deploy_probe_volume.sh`, unit soubory)
- Testy: `tests/test_learning_experiment_verdict.py`, `tests/test_learning_diagnostics.py`,
  `tests/test_learner_replay.py`, `tests/test_paper_probe_limits_env.py`,
  `tests/test_p0_8_plus_epoch_report.py`, `tests/test_paper_source_learning.py`,
  `tests/test_paper_learning_budget.py`

**Evidence (jen ke čtení)**
- `docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json`
  (915 obchodů, sha256 začíná `e9dcd1dfc95dbb63`) — hlavní snapshot
- starší: `…_20261026.json` (267), `epoch_20260925_closed_trades.json` (82)
- Reprodukce: `python -B scripts/research/p0_8_plus_epoch_report.py --json <snapshot> --out <dir>`
  a `python -B scripts/research/learner_replay_report.py --json <snapshot> --out <dir>`

## Otázky auditu

### A. Správnost měření
1. Odpovídají čísla v `_workspace/58_…` a `daily.md` snapshotu? Přepočítej klíčová.
2. Hrubý pohyb: počítá se z paper entry/exit cen. Jak paper executor plní (bid/ask,
   mid, slippage)? Může tím být hrubý edge systematicky zkreslen nahoru/dolů?
3. Jednotky: `pnl_pct × 100 = bps`, náklad 9 bps — sedí to s `PAPER_FEE_PCT=0.0008`
   a `PAPER_SLIPPAGE_PCT=0.0001`? Je 9 bps realistický proti Binance spot?
4. Intervaly většinou předpokládají nezávislé obchody (Welch, normální aproximace).
   Obchody se překrývají v čase a symbolu. Jak moc to podhodnocuje nejistotu?
   Je denní blokový bootstrap dostatečný?

### B. Platnost závěru „učení se nemůže zlepšit“
5. Jsou pět předpokladů v `learning_diagnostics.py` (hrubý edge, rozptyl kontextů,
   stálost, odhad vs výsledek, křivka) správně zvolené a správně spočítané?
   Ověř χ² homogenity s odhadnutými rozptyly a Wilson–Hilferty, kritickou ρ a
   naměřenou míru falešných poplachů (~8 % / 5 % / 2,5 %).
6. Je závěr „signály nemají informaci“ podložen, nebo by ho mohla způsobit
   agregace přes heterogenní strategie, režimy a období (Simpson, nestacionarita)?

### C. Replay a předregistrace
7. `learner_replay.py` aproximuje živé pravidlo: prior = globální průměr včetně
   vlastního kontextu (živě jen ostatní), EWMA po uzavřeních kontextu. Mění ty
   rozdíly závěr o záporném liftu?
8. Look-ahead: používá replay opravdu jen obchody uzavřené před vstupem? A co
   souběžné pozice ve stejném kontextu?
9. Je záporný lift skutečná anti-persistence, nebo artefakt: dělení podle mediánu
   se shodami, změna populace (probe profily od 23. 10.), výběrový efekt živého
   filtru na hodnocených datech, mean reversion vyvolaná TP/SL/timeout geometrií,
   časová konfundace?
10. Je předregistrace C1 poctivá (vznikla pohledem na stejná data)? Jsou čerstvá
    data po `prereg_after` srovnatelná, když se současně změnily limity, symboly
    (BNB, XRP, DOT), min. net a CONTROL = 1,0? Mohou historická data (jiný režim)
    zkreslit odhady pro čerstvá data? Je min. n = 300 dostatečné (síla testu)?
11. Plánovaný krok „potvrzeno → nasadit C1 jako živé pravidlo“: je rozhodovací
    pravidlo dost přísné? Co chybí (např. druhá replikace, korekce na závislost)?

### D. Proces agenta (hlavní část)
12. **Selhání autonomie:** pravidla S1→S2 určila přechod 28. 10., ale denní cron
    běžel jen v otevřeném sezení Claude a 12 dní neběžel. Je současné řešení
    (rozhodování na serveru přes systemd timer; cron v sezení jen pro zápis
    a notifikace) dostatečné? Kde jsou další jednobodová selhání?
13. **Změna pravidel uprostřed:** předem stanovená pravidla S2/S3 operátor 9. 11.
    zrušil; agent během 30 minut nasadil S2, vrátil S1, zvedl limity, změnil
    CONTROL podíl a předregistroval hypotézu. Byla ta sekvence rozumná? Co měla
    obsahovat (dokumentace rozhodnutí, oddělení kohort, čekání)?
14. **Review:** `CLAUDE.md` předepisuje vícenásobné nezávislé review před nasazením.
    Agent nasazoval změny kódu do běžícího PAPER bota jen s vlastními testy
    (402 cílených testů, kontrola v čisté kopii, záloha, validace konfigurace,
    automatický rollback). Je to přiměřené pro PAPER? Co chybí?
15. **Zdroj pravdy:** server neběží commit z gitu (kód nasazen soubory), lokální strom
    je záměrně „dirty“, agent commitoval jen vybrané soubory. Kopie reportu v
    `/opt/cryptomaster_research/code` se aktualizuje ručně. Jaké riziko driftu
    to vytváří a jak ho omezit?
16. **Dokumentace:** jsou `AGENTS.md`, `LOGIC.md`, remediation docs, `_workspace`
    reporty, `autonomy/*` a paměť agenta konzistentní? Najdi rozpory a zastaralé
    instrukce (např. `AGENTS.md` zakazuje commit, agent commituje a pushuje na
    pokyn operátora; `CLAUDE.md` popisuje starou architekturu).
17. **Komunikace výsledků:** jsou závěry agenta přiměřeně opatrné? Najdi místa,
    kde tvrdí víc, než data unesou, nebo naopak zamlčuje nejistotu.
18. **Zaměření:** dělá agent správnou práci vzhledem k cíli operátora (více dat +
    metriky, proč se učení (ne)zlepšuje)? Co by pro tento cíl udělal jinak?

## Výstup

Zapiš `_workspace/59_external_audit_learning_process.md`:

1. **Shrnutí** (max. 10 řádků): nejdůležitější nálezy a zda závěry agenta obstojí.
2. **Tabulka nálezů**: ID, oblast (A–D), závažnost (KRITICKÁ / VYSOKÁ / STŘEDNÍ /
   NÍZKÁ), stav (CONFIRMED / PLAUSIBLE / REFUTED / NOT_VERIFIED), důkaz
   (`soubor:řádek`, výpočet nebo příkaz), dopad.
3. **Přepočty**: které čísla jsi ověřil, jak, a s jakým výsledkem.
4. **Doporučení pro proces agenta**: konkrétní, proveditelná pravidla (co dělat
   jinak, kdy čekat, kdy žádat review nebo operátora), seřazená podle přínosu.
5. **Doporučení pro měření a učení**: co změnit v metrikách, replayi, předregistraci
   a sběru dat; co ponechat.
6. **Otevřené otázky pro operátora.**

Nepiš kód ani patche; pokud navrhuješ změnu, popiš ji a uveď test, který by ji ověřil.
