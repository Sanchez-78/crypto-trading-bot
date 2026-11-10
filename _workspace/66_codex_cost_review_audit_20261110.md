# Nezávislý audit cost/learning review — 2026-11-10

Audit commitu `1758da85a29107d34eaf0f39539391aba5e4025d` a aktuálního obsahu
`scripts/research/cost_and_learning_review.py`. Codex pouze audituje a radí;
implementace zůstává na Claude podle aktuálního AGENTS.md.

## Verdikt

**CHANGES_REQUIRED před použitím volitelných C1 vstupů.** Závěr nákladové aritmetiky
nad skutečným zmrazeným futures souhrnem není těmito nálezy zpochybněn. Ochrana C1
a validace vstupů však nejsou tak silné, jak uvádí report 65. Jde o integritu
výzkumu/reportů; nebyla nalezena cesta tohoto offline nástroje k obchodním příkazům.

Dosavadní běh bez `--c1-result` a bez `--c1-mu` sám o sobě není důkazem porušení
slepoty C1. Při tomto auditu nebyly otevřeny skutečné čerstvé outcomes ani znovu
vyhodnocen futures HOLDOUT. Reprodukce používají výhradně syntetická data.

## F01 — P1: soubor mu se načítá před kontrolou finálního C1

Místo: `scripts/research/cost_and_learning_review.py:226-232`.

`build()` nejprve načte report, C1 a `mu_path`. Až potom kontroluje, zda C1 vůbec
existuje, a zavolá `c1_section()`. Při C1=PENDING se mu načte a ignoruje. Bez C1
se mu načte ještě před vyvoláním chyby. Mu je agregát výsledků hodnocené kohorty,
tedy také outcome informace, nikoli neškodný slepý počet.

Reprodukce: loader spy v `cost_review_audit_20261110/reproduce.py` zaznamenal:

```text
PENDING: synthetic_report → synthetic_pending → synthetic_mu
výstup: status=PENDING, post_cutoff_outcomes_opened=false, mu_sha_recorded != null

Bez C1: synthetic_report → synthetic_mu → ReviewError
```

Není tvrzeno, že se hodnota mu při PENDING publikuje; problém je již nepovolené
načtení a nepřesný deklarovaný stav. Dosavadní test PENDING volá přímo
`c1_section(payload, None)`, takže pořadí I/O v `build()` nekontroluje.

Požadovaná oprava: ověřit autoritativní finální C1 před jakýmkoli čtením mu. Při
nepřítomném, PENDING nebo neověřeném výsledku mu vůbec neotevřít. Pole o přečtených
datech musí rozlišovat raw outcomes a outcome agregát a odpovídat skutečnosti.
Regresní test na úrovni build/CLI má při pokusu otevřít mu okamžitě selhat.

## F02 — P1: libovolný řetězec CONFIRMED nahrazuje ověření zmrazeného výsledku

Místo: `scripts/research/cost_and_learning_review.py:144-171`;
fixture `tests/test_cost_and_learning_review.py:32-36`.

Kontrola vyžaduje jen jeden ze tří finálních řetězců, neprázdný list ID a slovník
varianty. Nekontroluje manifest, očekávaný cutoff, shodu protokolu, unikátnost ID,
součty n, konečné lift/CI ani počet bloků. Nově vypočtený SHA souboru pouze
identifikuje přijatý obsah; neověřuje jej vůči důvěryhodnému manifestu.

Syntetický vstup byl přijat jako CONTRARIAN_CONFIRMED, přestože měl:

- cutoff 0;
- dvě shodná trade ID;
- upper_n=520 a lower_n=480, ale scored_n=2;
- bootstrap_blocks=0;
- chybějící lift a všechny meze CI.

Dosavadní pozitivní fixture sama obsahuje tři ID proti součtu skupin 1 000, a tedy
neověřuje realistickou konzistenci skutečného frozen C1. Stejná slabá kontrola
umožní následné přijetí mu po pouhé shodě hashe seznamu ID.

Požadovaná oprava: spotřebovávat a porovnávat důvěryhodný manifest/provenanci,
cutoff a schéma; validovat ID, counts, konečnost a uspořádání CI a dostupná metadata
podmínek předregistrace. Chybějící důkaz označit NOT_VERIFIED. Neimplementovat druhý
evaluator C1 a nepřepočítávat původní verdict; kontrolovat konzistenci dodaného
artefaktu. Pokud současný frozen formát potřebná metadata nenese, nedoplňovat je
odhadem. Přidat negativní testy chybného cutoffu/hash/n/ID/bloků a chybějících CI.

## F03 — P2: absence evidence je vykázána jako zdravá data

Místo: `scripts/research/cost_and_learning_review.py:115-128, 175-195`.

Vstup se třemi bloky obsahujícími pouze `statistics: {}` projde:
`futures_cost_table={}`, `coverage_gaps=0` a otázka použitelnosti dat dostane `OK`.
Chybějící coverage je tedy zaměněna za prokázanou absenci mezer. Úplnost hypotéz
a očekávané struktury reportu není ověřena.

Požadovaná oprava: validovat podporované schéma souhrnu a rozlišit prázdnou nebo
chybějící evidenci od platné coverage. Pro dokumentovanou částečnou rodinu či
NOT_VERIFIED výsledky zachovat explicitní stav; nikdy automatické OK. Otestovat
chybějící coverage, prázdné statistics a neúplné targety/symboly.

## F04 — P2: neplatný interval a n=0 vytvářejí ekonomické rozpočty

Místo: `scripts/research/cost_and_learning_review.py:95-110`.

`sensitivity()` ověřuje jen konečnost obou mezí, nikoli jejich pořadí. Syntetický
vstup `n=0, gross=1, ci95_net9=[5,-10]` dostal `gross_ci95=[14,-1]` a údajně
konzervativní rozpočet +11 bps, přestože bodový rozpočet je −2 bps a nejsou vzorky.
To není nález v původních skutečných výsledcích, ale chyba ochrany proti poškozenému
nebo chybnému vstupu.

Požadovaná oprava: lower <= upper; pro n=0 vracet nedostatek dat nebo chybu místo
odhadů. Pro výpočet z frozen dat ověřit jejich potřebné jednotky a konzistenci.
Nezavádět chybné pravidlo, že percentile CI musí vždy obsahovat bodový průměr.
Regresní test má tento obrácený interval odmítnout.

## Doplňky interpretace a budoucího plánu

1. **Maker nelze vyloučit jen rovností fee.** Aktuální veřejný standardní spotový
   sazebník skutečně uvádí maker=taker. Z toho plyne absence úspory na této složce,
   nikoli stejná cena a pravděpodobnost plnění. Spread capture, adverse selection,
   čekání a nevyplnění jsou další části ekonomiky. Tvrzení „maker má smysl jen na
   futures“ v reportu 65 je příliš silné. Z dosavadních dat ale stále není prokázáno,
   že spot maker překoná náklady. [Oficiální spot sazebník](https://www.binance.com/en/fee/trading).
2. **Spot shadow data neověří futures execution.** Mohou posloužit jako levná
   orientační kontrola, nikoli jako důkaz futures fill rate, spreadu, fronty nebo
   adverse selection. Ke skutečnému závěru je potřeba odpovídající instrument a
   point-in-time data; nelze jen vyměnit fee v existujícím spot experimentu.
3. **WR potřebuje explicitní definici.** `src/core/trade_metrics_contract.py:20-22,104-114`
   klasifikuje WIN až při net > +0,05 procentního bodu, tj. +5 bps; FLAT je pásmo
   ±5 bps. Futures screen `point_stats()` používá `net > 0`. Tyto dvě WR nejsou
   totožné metriky. Jen je pojmenovat a rozlišit, neměnit definice během C1 a
   nepřepočítávat kvůli tomu HOLDOUT.
4. **C2 potřebuje přesný jmenovatel primární metriky.** Rozdíl průměrů jen mezi
   uskutečněnými obchody po adaptivním filtrování není sám kauzálním účinkem
   randomizované alokace příležitostí. Před startem definovat analýzu podle původní
   alokace, zohlednění nepřijetí a sdílené kapacity; současně zvlášť uvést net/fill.
   Nezapisovat odmítnuté kandidáty jako obchody. Osnova replikace zatím není hotový
   protokol ke spuštění.

## Co kontrola potvrzuje

- `_calculate_pnl()` odečítá fee a slippage jednou; převod frakce na procenta
  je na `paper_trade_executor.py:1326-1333` konzistentní.
- Spot WS URL a použití midpointu v `market_stream.py` odpovídají popsanému rozdílu
  paper a executable ceny. Kvantitativní dopad výstupního spreadu nebyl nově měřen.
- Posun CI o konstantní cost a rozdělení mu podle skutečného q jsou algebraicky
  správné pro platné vstupy se správnou sémantikou.
- Nástroj neimportuje executor, runtime DB, Firebase ani síť.
- Profitabilita a nasazení nejsou automaticky schváleny pozitivním liftem.

Fee tier účtu, aktuální server env, serverový stav C1 a push na remote nebyly v
tomto auditu nezávisle ověřeny. Lokální commit 1758da8 existuje. Sazby futures 2/5 bps
jsou v oficiálním FAQ uvedeny jako příklad; pro konkrétní účet a nový experiment
je nutný aktuální příslušný sazebník. [Binance Futures FAQ](https://www.binance.bh/en-PH/support/faq/detail/360033544231).

## Ověření a předání implementátorovi

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_cost_and_learning_review.py -q --tb=short
rtk python -X utf8 -B _workspace/cost_review_audit_20261110/reproduce.py
```

- Existující cílená sada: **16 PASS**, izolovaná kopie; XML
  `_workspace/code_audit_20260921_r61xjvl7_results.xml`.
- Čtyři nálezy reprodukovány synteticky; úplný výstup
  `_workspace/cost_review_audit_20261110/reproductions.json`.
- Osm původních mutací z reportu 65 se zde znovu nespouštělo.
- SHA šesti runtime souborů a dvou auditovaných zdrojových/testovacích souborů
  před/po je shodný; doklad `cost_review_audit_20261110/integrity.json`.
- Auditovaný skript SHA-256:
  `dc4041064d9151c4b15ba0d115c224389a40b862aa54f9d1da8413f7d34ae0e1`.

Před použitím C1 vstupů doporučuji opravit F01/F02 a doplnit regresní testy, následně
F03/F04. Původní implementace ani testy nebyly tímto auditem změněny. Přibyly pouze
auditní důkazy a tento report; žádný deploy, restart, commit nebo reset.
