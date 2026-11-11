# C1 — postup pro den zmrazení a oddělení další kohorty

**Připraveno 2026-11-11; nyní NEPROVÁDĚT.** Nejbližší plánovaný běh, v němž může C1 skončit, je 2026-11-16 17:47 UTC, nikoli zaručený čas výsledku. Nutné jsou také alespoň 1 000 čerstvých obchodů, 16 různých 6h UTC bloků, 7 dní od cutoffu a 6 h od vstupu posledního hodnoceného obchodu. `PENDING` znamená čekat na další naplánovaný běh. Během čekání žádný restart bota, změna sběru, reset P/L/DB, aktivace opravy svíček ani čtení post-cutoff outcome dat.

Autorita: `docs/OPERATING_STATE.md`, předregistrace `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`, nasazení produceru `_workspace/76_c1_provenance_deploy_20261111.md`. Tento runbook nemění protokol C1.

## 1. Zmrazení: nejprve nezávislá reference

1. Po naplánovaném běhu zkontrolovat `STATUS` a pouze stavovou řádku `REPLAY`/`PROVENANCE` v `/opt/cryptomaster_research/verdict.log`. Při `PENDING` nebo selhání nepokračovat na výsledek; při selhání řešit `ALERT` bez otevření C1 outcomes. Nepouštět dodatečné iterace jen kvůli dřívějšímu výsledku.
2. Pokud vznikl finální `prereg_result.json`, nejprve převzít **přesnou** jedinou odpovídající řádku `PROVENANCE run=… manifest_sha256=… result_sha256=…` do nezávislého lokálního záznamu s časem převzetí a identitou serverového běhu. Před přečtením výsledku tuto referenci zachovat mimo přepisovatelný serverový log. Žádná řádka, dvě rozporné řádky nebo nejednoznačný `run` = **STOP / NOT_VERIFIED**.
3. Teprve pak bezpečně zkopírovat neměnné bajty `prereg_provenance.json` a `prereg_result.json`. Vypočítat SHA-256 přes **přesné bajty**, porovnat je s oběma hodnotami z již uložené řádky a také `result_sha256` uvnitř manifestu. Ověřit `contract=c1_provenance_v1`, `hypothesis=C1_contrarian`, očekávaný cutoff, `run_id`, finální verdikt a konzistentní hodnocenou množinu podle aktuální předregistrace. Statistiky nepřepočítávat a nepřepisovat zmrazený výsledek. Neshoda = **STOP / NOT_VERIFIED**; oprava svíček ani C2 se nespouští, dokud se původ nevyšetří.
4. Až po úspěšné verifikaci zapíše operátor přesnou řádku `PROVENANCE` a výsledné hashe do `docs/OPERATING_STATE.md` jako nezávislou referenci, včetně času, cesty k uloženým artefaktům a identifikace běhu. Záznam se verzovaně uloží mimo server. Žádný číselný závěr C1 se nepředjímá.

Skutečný výpadek hosta při zápisu nebyl simulován. I když serverový syntetický preflight produceru prošel, každý skutečný freeze musí projít vlastní hash kontrolou.

## 2. Oddělit řazení od ekonomiky

Po ověřeném zmrazení spusť `scripts/research/cost_and_learning_review.py` nad **kopiemi zmrazeného** výsledku a manifestu a nad historickým frozen futures screenem. Nový výstupní adresář použij při každém běhu; nástroj odmítá přepsat existující report. Lokální tvar:

```text
rtk python -B scripts/research/cost_and_learning_review.py --futures-report _workspace/futures_flow_20261109/screen/report.json --c1-result <kopie/prereg_result.json> --c1-provenance <kopie/prereg_provenance.json> --c1-provenance-sha256 <nezavisle_zaznamenany_manifest_sha256> --out <novy_vystupni_adresar>
```

Nejprve ověř `exposure` a `identity` v JSON: bez ověřeného původu je stav `NOT_VERIFIED` a nástroj nemá otevřít `mu`. Výsledek C1 může potvrdit **řazení**; sám neprokazuje kladný net vybrané politiky. Pro závěr o zisku je potřeba zvlášť důvěryhodný `c1_mu_v1` pro **přesně stejná ID, jednotky a náklady** a pak nový běh s `--c1-mu <kopie/mu.json>`. Pokud takový agregát není k dispozici, ziskovost zůstává `NOT_VERIFIED`; nevyrábět ji z liftu ani z chybějícího mu. Neotevírat znovu futures HOLDOUT ani měnit předregistrovaný verdikt. V reportu oddělit starých 9 bps modelu, alternativní nákladové scénáře a skutečnou neznámou fee tier/produktovou cestu.

**Rozhodnutí o paper nákladech po C1:** doporučený další model má vycházet ze skutečně zamýšleného produktu a účtového fee tieru, vstupní i výstupní bid/ask ceny, skluzu a případně funding/úroku. Oficiální [spot ceník Binance](https://www.binance.com/en/fee/trading) při kontrole 2026-11-11 uváděl pro běžný účet 0,10 % za stranu, s příslušnou BNB slevou 0,075 % za stranu; před aktivací jej znovu ověřit. Nejsou to automaticky sazby konkrétního účtu nebo futures. Současných 9 bps za celý obchod zůstane historickou definicí C1. Jakákoli změna paper cost modelu musí mít vlastní verzi a časový marker, testy a samostatnou kohortu; nedělat ji současně s opravou svíček nebo startem C2. Bez určení produktu/fee tieru a výslovného rozhodnutí operátora živý model neměnit.

## 3. Oprava svíček: až potom nová populace

Po verifikaci C1 a odděleném cost review lze spustit přípravu nasazení lokální opravy z `_workspace/63_codex_candle_refresh_fix.md`, **jen pokud** nezávislé review přesného diffu skončí `APPROVE`. Šest souborů opravy se 2026-11-11 shodovalo s `after.json`; před nasazením hashe spočítat znovu. Příznak `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED` zůstává do aktivace vypnutý. Neměnit limit 90 s, generátory, risk, TP/SL, náklady ani CONTROL současně s opravou.

**Aktuální blocker nasazovacího postupu:** `deploy/research_eval/deploy_bot_files.sh:28–35` nyní nepovoluje `candle_cache_v1.py`, `p0_8_plus_live_pipeline.py` ani nový příznak. Popis v `OPERATING_STATE.md:67–69` proto ještě není spustitelný. Neobcházet allowlist ručním kopírováním; nejprve připravit nejmenší rozšíření tohoto jediného skriptu a nezávisle reviewovat přesný diff skriptu i opravy. Do vyřešení blockeru žádné nasazení.

Při povoleném nasazení použít zálohu a rollback stávajícího skriptu, ověřit PAPER-only env, syntax, nulové otevřené paper pozice podle jeho preflightu a zaznamenat hash preimage/postimage. Před restartem zapsat plán nového `cohort_start_ms`; po úspěšné aktivaci zachytit skutečný čas, hash kódu/cache verzi a env příznak. **C1 hodnocená množina je výhradně seznam ID ve zmrazeném výsledku**, nikoli všechny obchody před nasazením. Obchody po novém markeru tvoří samostatnou kohortu opravené cache. Při rollbacku zaznamenat další marker; různé režimy nikdy tiše neslučovat. Restart jen existujícího bota, žádná další služba.

`deploy_bot_files.sh` vrací soubory a drop-in automaticky při chybě **během svého běhu**. Po úspěšném návratu ze skriptu už tato funkce neběží; pro později zjištěnou anomálii je třeba mít předem samostatně reviewovaný postup obnovy přesně těchto preimage souborů a drop-inu, kontrolu hashů a bezpečný restart. Samotná existence zálohy není hotový post-deploy rollback.

Po restartu ověřit zdraví služby, PAPER mode, REAL off, WebSocket, P0/risk/executor, datové stáří `data_age_ms`, počet fetch pokusů na symbol a UTC minutu, podíl `REJECT_STALE_MARKET_DATA` a funnel se **stejným jmenovatelem** před/po. Stale odmítnutí při skutečném výpadku upstreamu může být legitimní; cílem je odstranit závislost na minutové fázi, ne oslabit veto. Překročení rozpočtu REST, partial candle jako completed, zhoršená dostupnost nebo opakované chyby jsou důvodem k rollbacku s doloženou zálohou. Vyšší počet obchodů či změna P/L po opravě není účinek učení.

## 4. Rozhodovací větve a upozornění

- `CONTRARIAN_CONFIRMED` s ověřeným původem: otevřít pouze přípravu **jednoho** C2 testu podle `C2_REPLICATION_DRAFT_2026-11-11.md`. Nejdříve uzavřít jeho otevřené definice, power, náklady, code diff a nezávislé review. Politiku automaticky nepřepínat.
- `CONTRARIAN_REFUTED` nebo `CONTRARIAN_NOT_SHOWN`: C2 nespouštět; vyhodnotit učení na současných signálech v mezích C1 a nevyhlašovat obecné „učení nefunguje“. Oprava kvality svíček může pokračovat jako **samostatná** změna po review.
- `PENDING`, `INSUFFICIENT_DATA`, chybějící či rozporná provenience: žádné závěry ani změna bota; vyšetřit stav a čekat na platný pevný konec.

Server už má `ALERT` soubor a `OnFailure` pro výzkumné vyhodnocení, ale bez externího kanálu nedoručí oznámení operátorovi mimo aktivní sezení. Do výběru cílového e-mailu/Telegramu a schválení samostatného serverového doručování zůstává kontrola `STATUS`/`verdict.log` ruční. Žádný agentní Gmail závislý na sezení nevydávat za trvalé upozornění. Přidání externího kanálu vyžaduje vlastní malou změnu, ochranu credentials a test, že zpráva neobsahuje výsledky C1 před freeze.
