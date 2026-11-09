# Zapracování externího auditu `_workspace/59_…` (2026-11-09)

Autorita aktuálního stavu: `docs/OPERATING_STATE.md`. Tento soubor mapuje nálezy na kroky.

| Nález | Krok | Stav |
|---|---|---|
| F01 „učení nemůže fungovat“ | Errata v reportu 58; `LOGIC.md` přepsán („neprokázáno“, nulový souhrn nevylučuje výběr) | HOTOVO |
| F02 opakované pohledy na C1 | Dodatek 1 předregistrace: jediné vyhodnocení prvních 1 000 čerstvých obchodů po ≥ 7 dnech; do té doby `PENDING` bez výsledků (`learner_replay.evaluate_preregistered`) | HOTOVO |
| F03 akce závislé na sezení | Rozhodování o stupních zrušeno; session smyčka jen zapisuje a upozorňuje; serverový STATUS/ALERT | ČÁSTEČNĚ — chybí kanál k operátorovi |
| F04 rollback není transakční | `deploy_bot_files.sh`: trap ERR/INT/TERM → rollback, ověření hashů, READY po rollbacku | HOTOVO (bez fault-injection na serveru) |
| F05 míchání kohort | `run_eval.sh` vykazuje MAX_DATA kohortu zvlášť (`cohort/`, řádky `COHORT`, `LEARN_COHORT`) | HOTOVO |
| F06 `CURVE_IMPROVING` 36 % na šumu | Kód odstraněn, křivka jen popisná | HOTOVO |
| F07 V0 ≠ live | Označeno jako aproximace (kód, `LOGIC.md`, předregistrace) | HOTOVO (přejmenování ne — kvůli kontinuitě) |
| F08 příliš silné názvy | Kódy `*_NOT_SHOWN`, `NEGATIVE_*_SHOWN`; falešná pozitivita χ² uvedena | HOTOVO |
| F09 gross z asymetrických fillů | Uvedeno v `LOGIC.md` a errata | DOKUMENTOVÁNO; měření na pevných horizontech/BBO = budoucí úkol |
| F10 lift ≠ účinek politiky | Dodatek 1: potvrzení → jen replikační fáze po review, ne přepnutí | HOTOVO |
| F11 síla n = 300 | N = 1 000 (~80% síla pro 3,4 bps, iid) | HOTOVO |
| F12 „všichni kandidáti“ | Opraveno na „přípustní kandidáti“ (`LOGIC.md`, `OPERATING_STATE.md`) | HOTOVO |
| F13 přepisování běhů, ruční kopie kódu | Unikátní run ID, sdílený snapshot, `manifest.json` (SHA dat, výzkumného kódu, bota, env) | HOTOVO |
| F14 replay selže tiše | Každý krok `|| fail` → STATUS `FAILED`, exit 1, OnFailure alert; `latest` až po úspěchu | HOTOVO |
| F15 chybné „všechny intervaly obsahují 0“ | Errata | HOTOVO |
| F16 rozpory v dokumentech | `docs/OPERATING_STATE.md` jako index autority; superseded značky | HOTOVO |
| F17 chybí review | Nezávislé review přesného diffu (reviewer-agent): 1. kolo REJECT (únik C1 přes holdout V2 a cohort diagnostiku; journal check se SIGPIPE; děravé allowlisty; řazení drop-inů; nezmrazený výsledek; málo bootstrap bloků), 2. kolo APPROVE_WITH_FIXES (pokrytí 16 bloků při rychlém tempu) → opraveno (dodatek 1b/1c) | HOTOVO |
| F18 stará stage logika | `apply_stage.sh`, `stage_step.sh`, stage units odstraněny z repa i serveru | HOTOVO po nasazení |
| F19 validace replaye | Duplicitní ID / nekladná délka selžou; close jen přísně před vstupem | HOTOVO |
| F20 913/915 | Snapshot ID uveden v errata a manifestech | HOTOVO |
| Funnel telemetrie kandidátů | Nezahájeno — vyžaduje změnu bota a review | OTEVŘENÉ |
| Pevné horizonty / BBO | Nezahájeno | OTEVŘENÉ |
| Alert mimo sezení | Potřeba kanál od operátora | OTEVŘENÉ (otázka operátorovi) |

Provoz 2026-11-09 08:36 UTC: sběrný režim 1,08 h → 10 uzavřených obchodů (9,3/h,
symboly BTC, XRP, BNB, ETH, SOL), bez chyb v logu, disk 87 %. Tempo je pod krátkodobým
odhadem 18/h z 07:17–07:27; příčinu bez funnel telemetrie nelze určit.

Nasazení výzkumné části 2026-11-09 08:55 UTC (bot nerestartován): slepý běh
`20261109T085520Z` — epocha a replay jen do cutoffu (n = 921), C1 `PENDING` bez výsledků,
`COHORT_BLIND fresh_closed=11`; alert cesta otestována; timer znovu zapnut (17:47 UTC).
Časovač byl 08:45–08:56 UTC zastaven, aby starý kód nepočítal statistiky čerstvých dat.
