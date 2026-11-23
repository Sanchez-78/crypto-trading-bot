# Re-review nasazovacího kroku ECON BAD po D6–D8 — 2026-11-23

**Verdikt: APPROVE pro popsaný nasazovací krok.** Nálezy D6–D8 jsou v runbooku opravené. Schválení se týká připnutého artefaktu, stávajících deploy nástrojů a post-checku v `docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md`; skutečný stav serveru a výsledek nasazení jsem v tomto review neověřoval.

## Ověření oprav

- **D6, měřicí příkaz:** `:112–125` vytváří obě cesty přes `mktemp`; `trap` je odstraní při ukončení shellu. Souhrny se zapisují jen do unikátního dočasného souboru, pevná cesta `/tmp/econ_summaries.txt` zmizela. Návratový kód `journalctl` a neprázdný výstup se kontrolují před vyhodnocením počtů. Příkaz zachovává desetiminutové okno a `-o cat`; vypisuje i `MainPID`, aktivitu služby a krajní souhrny. Lokální `bash -n` je pouze autorem hlášený; Bash ani serverovou exekuci jsem v tomto review nespouštěl.
- **D7, identita a bezpečnost:** `:132–149` vyžaduje `MainPID` shodný s markerem `APPLIED OK`, stejný proces pro A/B a restart označuje `NOT_VERIFIED`. `src/services/realtime_decision_engine.py:763–767,803–837` skutečně resetuje `seq`, `since_s` a total při novém procesu. Runbook nyní explicitně vyžaduje `TRADING_MODE=paper_train`, `ENABLE_REAL_ORDERS=false`, `LIVE_TRADING_CONFIRMED=false` a příznak limiteru `true`; dostupnost journalu omezuje tvrzení o nepřítomnosti tracebacků. Tuto kontrolu musí operátor při nasazení skutečně vykonat: samotný měřicí skript PID jen vypíše a jeho shodu s markerem nevyhodnocuje automaticky.
- **D8, interpretace:** `:150–156` ponechává `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` jako kontext. Tři a čtyři výchozí události už nejsou práh úspěchu ani důkaz stejného rozhodování. Výchozí sazba 1 744,4 odmítnutí/min se používá pro srovnání, nikoli jako tvrdý tržně proměnlivý limit.
- **D4/D5 trvají:** z doručených souhrnů téhož procesu se počítá `N=Δtotal_rejects`, `S=Δtotal_suppressed`, `R=N/(Δsince_s/60)`; při výpadku souhrnu kumulativní rozdíl zůstává použitelný. Invarianty `0 ≤ S ≤ N` a `N−S ≤ 17×Δseq` odpovídají počítání v kódu. Pro každý detailní marker je provozní mez 17 na zasažené okno, nikoli počet kategorií z neúplných souhrnů. Při nedostatku dat zůstává účinek `NOT_VERIFIED`.

## Piny a rozsah

`git diff a5e6b64^ a5e6b64` mění jen `AGENTS.md`, zadání, předchozí report, podkladový oddíl a část „Po nasazení“ v runbooku. Lokální SHA-256 artefaktu `95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03`, deploy skriptu `981c88701f1e093cb1cedceb5637db6605971e23436843b44a32494c78397d29` a validátoru `927cc096afa2db380b2337825906ba6868afb6405d6e13ef346262e0bee351c5` sedí s piny. Read-only checker vrátil `ARTIFACT_BYTES_OK` a `COMMIT_BLOBS_OK`. Nasazovací příkaz se nezměnil. Živý serverový preimage musí před zápisem ověřit deploy skript.

## Neblokující poznámka

Pokud první `mktemp` uspěje a druhý selže, skript skončí ještě před instalací `trap` a zanechá první **prázdný** dočasný soubor. Je vhodné to při příští úpravě měřicího příkazu uklidit; neohrožuje to runtime data ani správnost nasazení. Výpočet N/S/R, kontrola PID vůči markeru a hledání tracebacků jsou v runbooku ruční kroky; výpis měřicího skriptu sám o sobě není automatický PASS.

Testy jsem u dokumentační změny znovu nespouštěl. Nebylo SSH, nasazení, restart, commit, push ani změna runtime dat. Skutečný post-deploy výsledek, retence journalu a zdraví služby zůstávají `NOT_VERIFIED` do provedení post-checku.
