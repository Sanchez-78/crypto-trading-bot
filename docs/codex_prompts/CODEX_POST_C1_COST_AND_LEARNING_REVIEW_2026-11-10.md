# CryptoMaster — náklady, důkazy o učení a příprava dalšího experimentu

Datum návrhu: 2026-11-10. Zadání pro následné samostatné spuštění Codexu.
Vytvoření tohoto dokumentu neaktivuje žádnou změnu bota ani experimentu.

## 1. Cíl a rozsah

Pracuj jako quantitative research engineer a Python reliability engineer v existujícím
CryptoMaster repozitáři. Konečný cíl operátora zůstává kladné post-cost P/L a WR > 50 %.
Nevydávej je za dosažitelné pouhým dalším trénováním. Úspěchem tohoto úkolu je správně
změřený rozdíl mezi kvalitou dat, schopností učení vybírat kandidáty a ekonomickou
ziskovostí, doplněný implementovanou lokální diagnostikou a konkrétním dalším postupem.

Toto zadání opravňuje k lokální práci ve fázi A. Fáze B je podmíněné čtení již
zmrazeného výsledku C1. Fáze C je pouze návrh dalšího experimentu k review.
Dokončení C1 samo nepovoluje nasazení, nový experiment ani změnu politiky.

Nevytvářej nový projekt, větev, worktree, bota, executor, službu ani nový learning engine.
Zachovej stávající root, aktuální větev a všechny cizí změny. Produkční root
`/opt/cryptomaster` a jeho služba zůstávají beze změny; zde se pracuje v otevřeném
lokálním workspace. Žádný SSH, deploy, restart, commit, push, reset, stash ani clean.

PAPER ONLY, REAL OFF. Neměň P0, RiskGuard, sizing, TP/SL, náklady používané botem,
symboly, limity, cooldown, CONTROL podíl, generátory, Stonkfly ani permissions.
Neresetuj P/L, DB, epochu, learning state ani Firebase. Nezvyšuj délku držení:
současných 900 s není důvod prodlužovat k historickému limitu 24 hodin.

Není požadován redesign aplikace, nové závislosti ani placené služby/datasety.
Proveď autorizované lokální kroky bez dotazů na jednotlivé implementační detaily.
Chybějící důkaz označ NOT_VERIFIED a dokonči nezávislé části práce.

## 2. Nejprve zjisti aktuální stav

Přečti `AGENTS.md`, `docs/OPERATING_STATE.md` a místní pravidla pro nástroje včetně RTK.
Zaznamenej HEAD, branch a git status. Rozsah oprávnění pro jiné agenty v provozních
dokumentech nepovažuj za oprávnění Codexu k serverovým zásahům.

Přečti alespoň:

- `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`, včetně všech dodatků;
- `RESEARCH_FUTURES_FLOW_FINDINGS.md` a `_workspace/64_codex_new_signal_source_screen.md`;
- `_workspace/futures_flow_20261109/screen/report.json`, `study.json` a doklady integrity;
- `_workspace/58_why_bot_does_not_improve.md`, zejména jeho errata;
- `_workspace/59_external_audit_learning_process.md`, `_workspace/60_audit_remediation.md`;
- `_workspace/63_codex_candle_refresh_fix.md`;
- `RESEARCH_PIVOT_CHARTER.md`, `RESEARCH_COSTWALL_FINDINGS.md`,
  `RESEARCH_LONGHORIZON_FINDINGS.md`, `RESEARCH_M5_COST_ARITHMETIC.md`.

Cesty ověř přes `rg`, nespoléhej na historický název. Zmapuj skutečné použití
`learner_replay.py`, `learner_replay_report.py`, `learning_diagnostics.py`,
`p0_8_plus_epoch_report.py`, `cost_model.py` a výpočtu closed trade P/L v existujícím
paper executoru. Čti kód; neimportuj moduly inicializující runtime DB nebo služby.
Tvrzení o živé cestě dolož dosažitelností z `start.py` přes `bot2/main.py`.

Staré hotové experimenty neopakuj. Rozliš:

- původní zaznamenané výsledky;
- aritmetické odvození z existujících souhrnů;
- nový exploratorní návrh;
- skutečně neověřené údaje.

## 3. Neporuš slepotu C1

Výsledek futures HOLDOUT je spotřebovaný. Nespouštěj znovu jeho simulaci, training,
bootstrap, výběr prahů, hledání podskupin nebo nové hypotézy. Neměň výpočetní skript,
předregistraci, stage soubory ani původní report 64. Čtení zmrazených souhrnů je povoleno.

U C1 nejdřív ověř stav pouze z povoleného slepého přehledu nebo lokálně předaného
autoritativního výsledku a manifestu. Nehledej automaticky čerstvé exporty/DB.
Chybějící důkaz ukončení = PENDING/NOT_VERIFIED, nikoli oprávnění výsledek dopočítat.

Do řádného zmrazení C1:

- žádné čtení čerstvých P/L, WR, MFE/MAE, score-outcome korelací, výsledků V2 ani
  jiného nepřímého proxy C1; C1 je opačné znaménko V2;
- žádné exploratory reporty nad kohortou po cutoffu;
- žádné změny sběru, oprava cache v produkci ani restart;
- pracuj jen s původními zmrazenými souhrny, historickým exportem do cutoffu,
  povolenými počty a syntetickými testovacími fixtures.

Známé podmínky C1 ověř proti aktuálnímu kódu a dodatku 1c: nejméně 1 000 čerstvých
obchodů, potřebný počet k pokrytí alespoň 16 různých 6h UTC bloků, nejméně 7 × 24 h
od cutoffu a alespoň 6 h od vstupu posledního hodnoceného obchodu. Kalendářní datum
16. 11. je orientační, nikoli automatické povolení. PENDING/INSUFFICIENT_DATA nejsou
zmrazeným závěrečným výsledkem. Původní statistickou metodu a rozhodovací pravidlo neměň.

Nalezneš-li nesoulad protokolu a implementace, zapiš nález a dopad, neprováděj během
C1 tichou opravu jeho evaluatoru nebo nové vyhodnocení. Nezávislé úlohy pokračují.

## 4. Fáze A1 — oprav interpretaci, nikoli historické výsledky

Do souhrnné dokumentace doplň krátké datované erratum. Neměň původní čísla ani
předregistrace. Oprav jen doložené formulace:

1. Ověřené ZIPy nejsou úplné časové řady. Z uloženého coverage ověř chybějící
   2026-10-28 ve futures všech sedmi symbolů a mezery metrics. Nevyplňuj je zpětně
   a nevytvářej druhý výsledek HOLDOUT. Odděl checksum integrity, coverage a input validity.
2. NO_EDGE se týká testovaných konfigurací a předpokladů. Neprokazuje vyčerpání
   všech veřejných dat nebo nemožnost učícího filtru. Počet 17 rodin není počet
   nezávislých statistických důkazů; některé principy a data se překrývají.
3. Nulový souhrnný gross nevylučuje rozlišitelné podskupiny. Jejich využitelnost musí
   být ověřena na nových datech; nehledat je dodatečně na spotřebovaném HOLDOUT.
4. Živý údaj +0,02 ± 1,34 bps je z paper fill cen, nikoli nutně mid-to-mid. Uveď
   přesný historický snapshot a interval, ne „přesně nula“ ani aktuální stav serveru.
5. Při pevných výstupech TP +35 / SL −25 a konstantním round-trip nákladu c platí
   `WR_BE = (25 + c) / 60`: 56,67 % pro 9 bps, 66,67 % pro 15, 71,67 % pro 18,
   75 % pro 20. Timeouty, gapy a jiné výstupy tuto dvoubodovou aproximaci porušují.

Přesnou WR po jiné ceně nákladů, PF či drawdown nelze dopočítat pouze z průměru.
Chybějící distribuci nenahrazuj dvoubodovým modelem ani vymyšlenými trades.

## 5. Fáze A2 — audit účetnictví a skutečných nákladů

Nejdřív sestav tabulku skutečných významů polí, jednotek a míst výpočtu. Odliš:

- očekávané náklady admission modelu;
- realizované/modelované náklady paper settlementu;
- fixní 9/18 bps výzkumného screenu;
- podmíněný odhad reálného execution pro konkrétní produkt a účet.

Prověř jednotky fraction / percent / bps: 0,01 % = 1 bps. Zapiš, zda jsou spread
a slippage již obsaženy ve vstupní/výstupní ceně. Neodečítej je podruhé.
Odděl entry/exit fee, spread, slippage, funding a případné další náklady. Zachovej
správné znaménko skutečného funding cashflow; konzervativní admission cost může mít
jinou sémantiku než settlement. Tyto dvě věci neslučuj bez důkazu chyby.

U poplatků potřebuješ venue, spot/futures, pár, maker/taker každé strany, tier,
slevu a její podmínky, datum účinnosti a oficiální zdroj. Nepředpokládej VIP tier,
BNB slevu, rebate, nulové fee nebo dostupnost produktu pro daný účet. Nečti secrets
a neposílej soukromé API dotazy. Neznámá sazba = NOT_VERIFIED, ne nula.

Veřejně ověřitelné údaje čerpej z primárních zdrojů, například:

- https://www.binance.com/en/fee/trading
- https://www.binance.com/en/fee/futureFee
- https://www.binance.com/en/support/faq/detail/5d3fa5e5709f47e0b5f186b350da1655

K 10. 11. 2026 veřejný standardní spot ceník uváděl 0,10 % maker/taker za stranu,
resp. 0,075 % s uvedenou BNB slevou; nejde o ověření našeho účtu. Při realizaci
ověř znovu. Spotové sazby nepřenášej na futures a dnešní sazby nevydávej za historicky
realizované náklady celé série. Běžný limitní příkaz nemusí být maker; post-only
zajišťuje maker charakter případného fillu, nikoli fill nebo profit.

Na zmrazených agregátech ukaž pouze aritmetickou citlivost při konstantních c
z množiny {0, 9, 15, 18, 20} bps. Nula je diagnostika, ne dostupná obchodní nabídka.
Pro všechny H1–H7 a oba targety uveď:

- n, původní gross a jeho existující interval;
- `net(c) = gross - c` a posun stejného intervalu o c;
- náklad bodu zvratu = mean gross;
- náklad slučitelný s rezervou +3 bps = mean gross − 3;
- konzervativní analogii z dolní meze gross CI, jasně označenou jako odvození.

Záporný rozpočet nákladů znamená, že požadovaná rezerva nevychází ani při nulových
nákladech. Neměň kvůli tomu rezervu nebo původní verdikt. Tento výpočet platí pro
stejné fills/signály; změna na maker mění i výběr a cenu fills, takže výsledek
nemůžeš extrapolovat jen odečtením menšího fee. Nevybírej další strategii podle
nejlepšího čísla v HOLDOUT. Variabilní náklady bez potřebných dat = NOT_COMPUTABLE.

Nalezený rozpor v core cost/settlement dolož souborem, řádkem a izolovaným příkladem.
Core v tomto úkolu neopravuj; připrav konkrétní nález k navazující opravě po review.

## 6. Fáze A3 — implementuj malý offline přehled

Nezůstaň jen u návrhu. Využij existující čisté reportovací funkce, pokud mají správnou
sémantiku a bezpečný import. Pokud vhodný konzument není, přidej:

- `scripts/research/cost_and_learning_review.py`;
- `tests/test_cost_and_learning_review.py`.

Jde o konzumenta existujících důkazů, nikoli nový simulator, evaluator C1, ledger,
cost model pro runtime nebo analytics službu. Neduplikuj existující bootstrap a replay.
Povoleny jsou jen stávající závislosti a syntaxe Python 3.12.

CLI přijímá explicitní cesty k frozen JSON souhrnu, případně výsledku C1 s manifestem,
a výstupní adresář. Žádné automatické hledání DB, network calls, Firebase, startup
hook ani import executoru. Bez C1 výsledku vypíše PENDING/NOT_VERIFIED a dokončí
cost review. Před otevřením jakýchkoli post-cutoff outcome dat musí ověřit oprávnění
z validního zmrazeného výsledku; v tomto úkolu nejsou taková raw data vstupem CLI.

Výstup JSON + čitelný český Markdown. Zahrň SHA-256 vstupů a kódu, zdroj jednotek,
verzi schématu, datum účinnosti fee scénáře, chybějící pole a přesný význam stavů.
Stejné vstupy musí dát stejné analytické výsledky. Nekopíruj přitom credentials/env.
Odmítni NaN/Infinity, duplicitní JSON klíče, neplatné counts/jednotky nebo poškozené
vstupy. Nedovol přepsat vstup nebo zaměnit frozen výsledek za nový report.

Přehled musí oddělit alespoň čtyři otázky, bez přidávání nových obchodních guardů:

| Otázka | Co je důkaz | Co nestačí |
|---|---|---|
| Jsou data použitelná? | provenance, coverage, časová dostupnost | počet souborů |
| Umí learner lépe seřadit kandidáty? | původní C1 verdict a intervaly | více obchodů |
| Má vybraná politika kladný net? | samostatný odpovídající OOS důkaz | kladný lift |
| Je připravena změna bota? | nový protokol, review, autorizovaná replika | zelené unit testy |

Chybějící důkaz o profitabilitě nesmí přejít na PASS při C1 CONFIRMED. Žádný stav
tohoto reportu nesmí aktivovat trading, měnit readiness nebo přepisovat centrální P0.

## 7. Fáze B — pokud již existuje řádně zmrazené C1

Jenom přečti autorizovaný existující výsledek. Ověř shodu cutoffu, manifestu, protokolu,
ID hodnocené množiny a potřebných metadat. Nevyvolej první vyhodnocení, nepřepočítej
verdict a nepřidávej další varianty C1. Není-li možné provenanci ověřit, reportuj to.

Zobraz původní lift, oba existující intervaly, n a počty 6h UTC bloků. Pole
`day_bootstrap` historicky obsahuje 6h bloky — neoznačuj je za celé dny. Počty
`upper_n` a `lower_n` používej skutečné: pravidlo `score > median` vs. `<= median`
může kvůli shodným scores vytvořit nestejně velké skupiny.

Samotný zmrazený C1 výsledek nemusí obsahovat průměrný net horní/dolní skupiny.
Nevymýšlej jej ani jej nenahrazuj průměrem jiné epochy. Pokud je k dispozici
důvěryhodný agregát průměru mu pro přesně tutéž množinu, lze aritmeticky odvodit:

`q = upper_n / (upper_n + lower_n)`

`mean_upper = mu + (1 - q) * lift`

`mean_lower = mu - q * lift`

Bez mu je výsledek NOT_VERIFIED. Z marginálních CI mu a liftu nevyráběj CI pro
mean_upper; k tomu je potřeba společná nejistota. Příklad pro vysvětlení, ne výsledek
C1: při mu = −9, q = 0,5 a lift = +4 bps je mean_upper = −7 bps.

Interpretace:

- CONFIRMED = evidence lepšího pořadí v této populaci, podklad k návrhu replikace;
- REFUTED = protisměrná hypotéza v testu neobstála; automaticky nepřepínej na její opak;
- NOT_SHOWN = účinek nebyl prokázán, nikoli důkaz přesné nuly;
- PENDING/INSUFFICIENT_DATA = žádný závěr ani implementace nové politiky.

Pořadí kolem mediánu celé uzavřené kohorty je ex-post diagnostika. Není to causal
vstupní filtr, který by šel převzít do online bota s použitím budoucího mediánu.

## 8. Fáze C — konkrétní plán po C1, pouze k review

### C1: oprava kvality dat

Ověř existenci hotového diffu opravy cache/reportu 63; nepřepisuj jej a netestuj
zbytečně znovu již uzavřenou práci. Do plánu uveď podmínky nezávislého review,
samostatného povoleného nasazení po C1, preflight a rollback. Zachovat limit 90 s,
jen dokončené svíčky a stávající limit stahování. Příznak zůstává nyní vypnutý.

Ověření po případném budoucím nasazení: stáří dat, počet stahování za symbol/minutu,
podíl stale rejections a funnel počty se stejným jmenovatelem. Oprava mění populaci
kandidátů, proto musí mít nová kohorta vlastní čas/version marker. Neslučuj ji s C1
a nevydávej zvýšení počtu obchodů nebo změnu P/L za účinek učení.

### C2: replikace učení pouze při odpovídajícím důkazu

Připrav nejvýše jeden DRAFT protokol replikace, který zůstane neaktivní. Pokud C1
není známý, připrav jen podmíněnou osnovu; nepoužívej odhadovaný výsledek.

Protokol musí předem určit:

- hypotézu, novou kohortu, datum cutoffu, verzi kódu a neměnný cost model;
- jednu kauzálně proveditelnou mapu score → přijetí, bez budoucího mediánu;
- původ kalibrace, tie handling a pravidla dostupnosti uzavřených outcomes;
- baseline se stejnými kandidáty a existující risk/execution cestou;
- kontrolní alokaci před výsledkem, její pravděpodobnosti a stabilní decision IDs;
- oddělené jmenovatele: příležitosti, přijaté kandidáty, fills a closed trades;
- vliv sdílené kapacity portfolia a aktualizace společného learning state;
- primární metriku a nejmenší ekonomicky zajímavý účinek, fixed end, potřebné
  časové bloky a konzervativní power odhad se závislostí obchodů;
- náklady, nejistotu, WR, PF, drawdown, gross/net a zamítnuté příležitosti;
- jediný závěrečný výsledek; žádné prodlužování do zisku nebo předčasné nahlížení.

Vybranou podskupinu a zbytek nenazývej automaticky randomizovaným A/B testem.
Odmítnuté kandidáty nezapisuj jako fiktivně uzavřené pozice. Hypotetické outcomes,
pokud je někdy schváleno jejich měření, nesmí kontaminovat portfolio statistiky.
Nepřidávej paralelní executor. Kladný lift a kladný post-cost EV vyhodnocuj odděleně.

### C3: další směr výzkumu jen po levném ověření proveditelnosti

Nespouštěj další grid search. Seřaď nejvýše dvě věcně odlišné možnosti pro rozhodnutí
operátora podle existujících důkazů; varianta „zatím žádná“ je přípustná.

U maker směru je nutné doložit dostupné fee, queue/partial-fill předpoklady, fill rate,
latenci, adverse selection, cost exitů a výnos od skutečného fillu. Dotyk midpointu
není fill. Nízká frekvence sama strategii nevyvrací; rozhoduje výnos, nejistota a
ekonomika na fill i příležitost. Optimistický maker model neopravuj jen snížením fee.

U jiného zdroje/trhu popiš konkrétní mechanismus predikce, point-in-time dostupnost,
licenci, survivorship bias, historické universe, očekávanou velikost pohybu a celkové
náklady. Placená data ani menší pár nejsou důkazem edge. Žádný nákup, nová market
pipeline nebo runtime implementace, dokud není nový protokol a samostatný souhlas.

Použij charter jako výzkumnou podmínku, nikoli automatickou změnu P0: realistický
post-cost výsledek s rezervou, kladná dolní mez, dostatek nezávislé časové evidence,
PF, režimy a koncentrace. Nový test potřebuje nová ověřovací data. Starý HOLDOUT lze
označit jako již známý, nelze ho znovu prohlásit za neviděný.

Stonkfly zůstává ve své současné shadow/context roli. Nepřidávej nové inference
instance, přímé objednávky nebo sizing podle confidence. Jeho případný budoucí
přínos musí být měřen oproti stejné politice bez kontextu na nových datech; takový
experiment není automaticky součástí tohoto zadání.

## 9. Testy a omezený diff

Povolené nové kódové soubory jsou jen offline report a jeho test výše. Nejdřív ověř,
že neexistuje odpovídající nástroj; pokud existuje, rozšiř jej minimálně a v reportu
vysvětli volbu. Žádné změny live modulů nebo frozen experimentů.

Dokumentační errata smějí být v `RESEARCH_FUTURES_FLOW_FINDINGS.md` a úzce vymezené
interpretaci výzkumu v `docs/OPERATING_STATE.md`. Neměň provozní stav, autorizace,
cutoffy ani freeze. Výstupy práce piš do `_workspace/65_codex_cost_and_learning_review.md`
a `_workspace/cost_and_learning_review_20261110/`. Existující obsah zachovej.

Spouštěj pouze `tests/test_cost_and_learning_review.py`; při nezbytném rozšíření
existujícího reportu navíc odpovídající `tests/test_learner_replay.py`,
`tests/test_replay_blinding.py` nebo `tests/test_p0_8_plus_epoch_report.py`, pouze
pokud takový soubor skutečně existuje a týká se změny. Celou sadu nespouštěj.

Testy musí ověřit alespoň:

1. správnou konverzi percent/fraction/bps a oddělení jednostranného/round-trip fee;
2. gross/net aritmetiku a neodečtení spreadu již obsaženého ve fill ceně;
3. dvoubodový WR_BE a zákaz jeho vydávání za přesný práh při timeoutech;
4. konstantní posun již existujícího CI, bez nového bootstrapu HOLDOUT;
5. nemožnost odvodit WR při novém nákladu, PF nebo DD z pouhého průměru;
6. kladný lift spolu se záporným net neznamená ziskovost ani execution eligibility;
7. nestejné median skupiny, správné q a odmítnutí chybějícího/skupinově odlišného mu;
8. PENDING, poškozený nebo neověřený C1 vstup neotevře post-cutoff outcomes;
9. 6h bootstrap bloky nejsou v novém reportu označené jako dny;
10. determinismus, provenance, chybějící pole, NaN/Infinity a duplicitní JSON klíče;
11. pokus přepsat vstupní/frozen soubor selže;
12. žádný import runtime DB, executor call, Firebase write ani síťový požadavek.

Ověř důležité negativní testy mutací pouze v izolované kopii; nepřepisuj skutečné
frozen soubory. Fixtures používej jen v tmp_path. Využij existující bezpečný izolovaný
runner, pokud kořenový conftest může sahat na runtime.

Před a po testech porovnej SHA šesti runtime souborů předepsaných AGENTS.md.
Rozdíl je incident: zastav mutace a nahlas jej, nic neobnovuj přepsáním evidence.
Zkontroluj i hashe původního futures skriptu, jeho předregistrace a stage výsledků.
Syntax ověř bez bytecode pro Python 3.12; lint jen pokud je dostupný. Kontroluj diff
po každé fázi a nezahoď žádnou cizí změnu.

## 10. Výstup a dokončení

Report 65 musí uvést:

- rozsah změn a stav C1 s datem/zdrojem, nikoli odhad aktuálního serveru;
- ověřené problémy oddělené od předpokladů, každý s konkrétním důkazem;
- mapu admission/paper/research nákladů a nevysvětlené rozdíly;
- odvozené cost tabulky a jasné omezení agregovaných vstupů;
- původní C1 verdict, pokud je dostupný, oddělený od profitability;
- seznam souborů, testy PASS/FAIL/NOT_RUN, mutace a integrity před/po;
- priority návrhů: nyní lokálně / po C1 k review / nový experiment s novými daty;
- konkrétní příkaz k bezpečnému opakování reportu ze stejných frozen vstupů;
- co nebylo ověřeno a jaký přesný důkaz chybí.

Hotovo znamená: lokální diagnostika funguje a je otestovaná, interpretace je přesná,
frozen experimenty a runtime data jsou beze změny, C1 nebyl odslepen nebo znovu
vyhodnocen a návrh dalšího kroku je konkrétní. PENDING C1 nebrání dokončení fáze A.
Žádný nový obchod, reset ani nasazení nejsou součástí Definition of Done.

V závěru stručně sděl výsledky, odkazy na artefakty a podmínky dalších kroků.
Neoznač žádnou hypotézu za ziskovou jen proto, že prošly testy nebo má lepší pořadí.
Nevytvářej slib, že více obchodů, delší trénink nebo Stonkfly zajistí P/L+.
