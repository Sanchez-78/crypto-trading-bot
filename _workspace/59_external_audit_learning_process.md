# Externí audit vyhodnocování učení a procesu agenta — 9. 11. 2026

## 1. Shrnutí

1. Závěr „přínos současného filtru nebyl prokázán“ obstojí; „signály nemají žádnou informaci, učení se nemůže zlepšit“ neobstojí.
2. Snapshot má 915 unikátních obchodů, −8,9782 bps net/obchod; ADAPTIVE−CONTROL +1,3865 bps, orientační 95% CI [−1,4244; +4,1973].
3. Všech 802 uložených odhadů, počtů a hashů trénovací historie lze rekonstruovat: adaptace není pouze nápis v dashboardu.
4. Replay skutečně dává záporné holdout lifty, ale není přesnou simulací živé politiky ani jejího portfolia; srovnávací citlivosti znaménko V0 nezměnily.
5. C1 je legitimní nová hypotéza, nikoli potvrzený objev; chybí pevný konec testu, ošetření opakovaných pohledů, závislosti a přenosu do admission politiky.
6. `CURVE_IMPROVING` vzniká v 36,1 % nulových simulací; některé další názvy diagnostiky zaměňují nedostatek důkazu za důkaz absence.
7. Serverový timer zajišťuje výpočty, ale aktuální akce/notifikace opět závisejí na otevřeném sezení; nové deploy skripty nemají úplný transakční rollback.
8. Doporučení: pokračovat ve sběru PAPER dat, oddělit nové kohorty a důkazní pravidla; virtuální ztrátu nepovažovat za důvod zastavení tohoto experimentu.
9. Audit nic nenasazuje ani nemění v produkčním kódu: 245 cílených testů PASS, šest runtime SHA a všech 609 kontrolovaných souborů beze změny.

## Rozsah, metoda a zdroj pravdy

Zadání: `docs/codex_prompts/EXTERNAL_AUDIT_LEARNING_PROCESS_2026-11-09.md`.
Lokální větev `main`, HEAD `9e682ff489570c159ce65cc5cd821799bc004524`.
Dirty pracovní strom byl zachován. HEAD není identifikací celého aktuálního stromu ani serverového release.
Primární evidence:

```text
docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json
SHA256 e9dcd1dfc95dbb63c82ad9310253abe6b2e4125c128db55d4c9a26b5b5cb01d6
915 řádků / 915 unikátních trade_id
první entry 2026-09-25 10:01:38.058716 UTC
poslední exit 2026-11-09 06:41:52.375488 UTC
```

Snapshot **neobsahuje žádný obchod po `prereg_after=1794209516`**, tj. po 9. 11. 07:31:56 UTC.
Nový provozní režim a jeho přínos proto nelze z těchto dat ověřit.
Serverové PID, skutečně instalované unit soubory, efektivní env, poslední serverový report,
aktivitu cronů a doručení notifikací hodnotím `NOT_VERIFIED`: SSH nebylo použito.
Citované provozní události jsou doložené místními zápisy, nikoli novým serverovým měřením.
Úplná historie konverzací a paměti Claude není v auditních podkladech; z absence dokladu
nevyvozuji, že oprávnění nebo review určitě neexistovalo.

Ověřená dosažitelnost v místním kódu:

```text
start.py:48 → bot2/main.py:1718–1719
  → p0_8_plus_live_pipeline.run_live_tick
  → p0_8_plus_shadow_evaluator.evaluate_symbol
  → signal_router.py:354 → paper_source_learning.evaluate/decide
  → risk guard (signal_router.py:380) → paper executor
  → canonical closed_trades → read_outcomes (paper_source_learning.py:382)
```

Stonkfly je oddělený shadow/context poskytovatel. Diagnostika a replay jsou offline moduly,
volané výzkumnými skripty; nejsou samostatným trading executorem. `evidence_budget` je
rozpočtové pravidlo s výslovně orientačními mezemi, nikoli důkaz profitability.
Zrušení stop politiky pro PAPER sběr samo o sobě není bezpečnostní nález ani chyba učení.

Pro procesní část použit skill `diagnose` a jeho základ `agent-workflow`; aktuální zadání
má přednost před historickými pokyny k deploy. Veřejná sazba poplatků byla zvlášť ověřena
na oficiálních stránkách Binance. Žádné přihlášení k účtu, cloudové čtení nebo zápis.
Výpočtové pomocníky a artefakty jsem vytvořil pouze pod `_workspace/external_audit_20261109/`.

## 2. Tabulka nálezů

Závažnost znamená dopad na platnost experimentu nebo spolehlivost procesu, nikoli
velikost virtuální ztráty. **KRITICKÝ nález povolení reálných objednávek nebyl v tomto
omezeném auditu prokázán; aktuální serverové guardy nebyly kontrolovány.**

| ID | Oblast | Závažnost | Stav | Důkaz | Dopad |
|---|---|---|---|---|---|
| F01 | B/D | VYSOKÁ | CONFIRMED | `_workspace/58_why_bot_does_not_improve.md:9`, `:33`, `:51`; `LOGIC.md:237`; kontrapříklad v `extra_results.json` | Nezamítnutí nulové hypotézy je prezentováno jako nemožnost učení; nulový nepodmíněný gross nevylučuje užitečný výběr. |
| F02 | C/D | VYSOKÁ | CONFIRMED | `learner_replay.py:188`, `:200`; `run_eval.sh:76`; `LOOP.md:18`; předregistrace `:24`, `:33` | C1 se opakovaně hodnotí po dosažení minima bez pevného konce/alpha spending; první kladný interval může spustit nasazení. |
| F03 | D | VYSOKÁ | CONFIRMED | `LOOP.md:18`, `:28`; `stage_step.sh:9`; `state.json:5`; eval unit bez OnFailure | Aktuální C1 akce, upozornění a obnova cronu závisejí na sezení; původní jednobodové selhání autonomie není celé odstraněno. |
| F04 | D | VYSOKÁ | CONFIRMED | `deploy_bot_files.sh:67–71`, `deploy_probe_volume.sh:66–70`, `apply_stage.sh:74–81` | Selhání při instalaci dalšího souboru/zápisu drop-inu/daemon-reload ukončí `set -e` skript bez rollbacku; slib „on any failure“ neplatí. |
| F05 | C/D | VYSOKÁ | CONFIRMED | `profile_signature():163–171`, `LOGIC.md:235`, `daily.md:7–12`; report groups podle policy version | Změna frekvence, symbolů a CONTROL podílu nemění cohort podpis; bez dalšího časového/config filtru může souhrnný ADAPTIVE−CONTROL míchat historické a nové populace. |
| F06 | B/D | VYSOKÁ | CONFIRMED | `learning_diagnostics.py:170–172`, `LOOP.md:25`; vlastní 1 000 simulací | `CURVE_IMPROVING` není statistický test: 361/1 000 falešných označení na šumu, nikoli zhruba 5 %. |
| F07 | C | STŘEDNÍ | CONFIRMED | `learner_replay.py:81–102` proti `paper_source_learning.py:310–318`, `:389–413` | V0 používá globální prior včetně vlastního kontextu, bez cohort/provenance filtru a limitu 500; název „current“ přeceňuje shodu s live. |
| F08 | B | STŘEDNÍ | CONFIRMED | `learning_diagnostics.py:97–106`, `:155–169`; null simulace | χ² s odhadnutými rozptyly má vyšší falešnou pozitivitu; `NOISE_ONLY`/`UNINFORMATIVE` jsou příliš silná označení negativního testu. |
| F09 | A | STŘEDNÍ | CONFIRMED | `p0_8_plus_live_pipeline.py:339`, `market_stream.py:84`, `paper_trade_executor.py:2918`, `:2955` | Entry překračuje spread, exit bere midpoint. „Gross před náklady“ není čistý mid-to-mid signál ani plně realizovatelný round trip. Velikost odchylky ze snapshotu nelze změřit. |
| F10 | C | STŘEDNÍ | CONFIRMED | `learner_replay.py:142–157`; předregistrace `:30–32` | Lift horní vs dolní poloviny není účinek sigmoid admission, počet obchodů/h ani výsledek portfolia; přenos C1 do živé policy není specifikován. |
| F11 | C | STŘEDNÍ | CONFIRMED | Předregistrace `:24`; výpočet síly testu v `independent_results.json` | n=300 má při SD≈18,91 bps 80% sílu až pro lift≈6,12 bps za optimistické nezávislosti; není univerzálně „dost dat“. |
| F12 | C/D | STŘEDNÍ | CONFIRMED | `LOGIC.md:249–251`, předregistrace `:20–22`, `paper_source_learning.py:436–443`, router `:380` | CONTROL=1 vypíná pouze adaptivní odmítání. Pacing, risk, quote, generátor a obsazenost stále vybírají obchody; „všichni kandidáti“ a „libovolné pravidlo férově“ jsou nepřesné. |
| F13 | D | STŘEDNÍ | CONFIRMED | `run_eval.sh:15–16`, `:24`, `:34`, `:79`; generic deploy nemá SHA manifest | Dva výpočty denně přepisují stejnou složku; ruční kopie reportového kódu není svázána s nasazeným learnerem a data snapshot není součástí release identity. |
| F14 | D | STŘEDNÍ | CONFIRMED | `run_eval.sh:79–85`, eval service `:14`; `LOOP.md:12–13` | Replay může selhat, skript přesto skončí úspěšně. Starý replay může zůstat vedle nového reportu; nezávislé doručení alertu není implementováno v předložených units. |
| F15 | A/D | STŘEDNÍ | CONFIRMED | Report 58 `:24–25`; přepočet source×side a symbol | Tvrzení „všechny gross intervaly obsahují nulu“ není pravda: legacy MR BUY má záporný interval, BTC slabě kladný. Po mnoha testech to neprokazuje edge. |
| F16 | D | STŘEDNÍ | CONFIRMED | `AGENTS.md` zákaz commit/deploy; `LOOP.md:19`, `:27`; `CLAUDE.md` CORE/HARNESS; report 58 `:68` | Provozní návody se rozcházejí v autoritě, architektuře a aktuální etapě; historická pravidla mohou být znovu omylem vykonána. |
| F17 | D | STŘEDNÍ | PLAUSIBLE | `CLAUDE.md` „No deployment without all agent approvals“; 9. 11. materiály neobsahují konkrétní review attestaci | Riziko self-review u změny experimentálního designu. Absenci review 9. 11. ani úplnost deklarovaných 402 testů nelze nezávisle potvrdit. |
| F18 | D | STŘEDNÍ | CONFIRMED | `apply_stage.sh:53–58`, `:84`; generic deploy `:51–56`, `:73`; `stage_step.sh:7–19` | Kontrola nulových pozic není quiescence barrier; chybí společný deploy lock a ochrana před starým next_action. Aktivace starého stage timeru by byla riziková. |
| F19 | C | STŘEDNÍ | CONFIRMED | `learner_replay.py:87`, `:163`, `:188`; fixture `extra_results.json` | Replay přijme nulovou délku a použije vlastní outcome před odhadem; prereg API nevaliduje záporné délky ani duplicity ID. V dodaných 915 řádcích se to nevyskytuje. |
| F20 | A | NÍZKÁ | CONFIRMED | Report 58 `:3`, `:22`, `:29`; přepočet prvních 913 closes | Report míchá 913/915 a 807/809 párů bez přesného snapshot ID. Rozdíl +1,46 vs +1,39 je vysvětlitelný dvěma novými obchody, ne chybou vzorce. |
| F21 | A | NÍZKÁ | REFUTED | Vlastní bootstrap 1/2/3/7 dnů, 226 překryvů mezi symboly, 0 v témže symbolu | Zde není doloženo, že normální CI musí být užší než blokové nebo že se překrývají pozice stejného symbolu. Závislost dál omezuje kauzální výklad. |
| F22 | C | NÍZKÁ | REFUTED | Holdout V0/V2: 366 unikátních odhadů, 0 shod na mediánu; citlivosti priors | Shody mediánu a přimíchání vlastního kontextu do prioru nevysvětlují záporný lift v tomto snapshotu. Nevyvrací to jiné confoundery. |
| F23 | D | NÍZKÁ | REFUTED | Report 54 `:140`, report 56 `:125`, `:139`; historické review artefakty | Plošné tvrzení, že všechny dosavadní releasy měly pouze autorovy testy bez review, neodpovídá uloženým říjnovým reportům. |
| F24 | A/D | NÍZKÁ | NOT_VERIFIED | Žádný nový přístup na server ani účet | Aktivita timerů, aktuální REAL guardy, rychlost nového sběru, dostupnost Firebase/quota a skutečná sazba účtu zůstávají mimo důkazní rozsah. |

## 3. Přepočty a odpovědi A–C

### A1. Čísla, účetnictví a různé snapshoty

Nezávislý výpočet používá `pnl_pct × 100`, výběrovou SD, side-aware návratnost
`sign × (exit/entry − 1) × 10 000`, SciPy Pearson/Spearman a vlastní bootstrap.
Vedle něj byly spuštěny oba původní CLI reporty, aby se ověřila reprodukovatelnost.

| Metrika | Výsledek auditu | Posouzení |
|---|---:|---|
| Celkový net / obchod | −8,978175 bps, 95% CI [−10,313771; −7,642579] | Souhlas s −8,98 |
| Celkový gross / obchod | +0,021799 bps, 95% CI [−1,313792; +1,357390] | Souhlas s +0,02 ±1,34; není to „přesně nula“ |
| P/L součet | −6,1612725 USD | 915 obchodů; nejde o dřívější −2,04447 USD/267 |
| Implikovaný odečet gross−net | 8,999974 bps v průměru | Odchylky řádků odpovídají zaokrouhlení P/L |
| ADAPTIVE | n=355; −7,668535 bps | Native policy |
| CONTROL | n=341; −9,054985 bps | Native policy |
| Rozdíl | +1,386450 bps; z/Welch SE CI [−1,424368; +4,197269] | `SELECTION_EFFECT_NOT_SHOWN` |
| Původní denní bootstrap rozdílu | [−1,289530; +4,094180] bps | 20 pozorovaných dnů, 18 společných, 2 000 validních replikací |
| Původních 913 closes | A/C=354/340; +1,458263; CI [−1,358801; +4,275327] | Reprodukuje report 58 a zápis S2 |
| Predikovaný gross vs realizovaný | n=809; Pearson +0,046086; Spearman −0,079021 | Report má n=807 ze staršího prefixu |
| MFE≥10 / MAE≤−10 bps | 51,5847 % / 52,3497 % | Blízké reportu; symetrie sama nedokazuje náhodnou procházku |
| Native diagnostika | 765 tagovaných trades, 752 non-WARMUP | Nezaměňovat s 915 celkem |
| Disperze kontextů | k=15, n=704; Q=10,156120, df=14 | WH p=0,751556; přesné χ² tail p=0,750683 |
| Stabilita těchto kontextů | Pearson −0,347280; Spearman −0,192857 | Reprodukuje daily.md |
| Native odhad vs outcome | n=752; Pearson −0,091662; Spearman −0,106982 | Reprodukuje −0,11 |
| Rozdíly po čtvrtinách | +2,866492 / +2,562209 / +1,023908 / −1,245996 bps | Reprodukuje daily.md; nejde o test trendu |
| Širší context grouping bez policy podpisu | 36 kontextů, 17 s n≥20; Pearson −0,338610 | Vysvětluje reportových −0,34/17 oproti −0,19/15; jiná metrika/populace |
| Stonkfly policy | 37 trades: 12 WARMUP, 24 PROBE, 1 ADAPTIVE, 0 CONTROL | Užitnost neural kontextu nelze posoudit A/B |

`daily.md:5` souhlasí s dostupným snapshotem. Přibližných 47 obchodů/24h nemá
v zápisu přesně specifikovaný okamžik a filtr, proto tento počet neoznačuji za přesně
reprodukovaný; totéž platí pro ~18/h a první tři vstupy po 07:17, které export předcházejí.

Dvě konkrétní opravy blanket tvrzení reportu 58:

- `sideways_mean_reversion_v1 / BUY`: n=41, gross −8,308848 bps,
  normální 95% CI [−16,404217; −0,213479]. Ne všechny source×side intervaly obsahují nulu.
- BTCUSDT: n=198, gross +2,350836 bps, CI [+0,063382; +4,638291].
  Ani zde neplatí „vše v šumu“ při použitém jednotlivém normálním testu.
  Jde o mnoho následně prohlížených podskupin, ne předregistrovaný objev.
  Navíc BTC net je přibližně −6,65 bps; uvedený hrubý výsledek není ziskovost.

### A2–A3. Co skutečně znamená gross a náklad 9 bps

Entry v `p0_8_plus_live_pipeline.py:339` je ask pro BUY, bid pro SELL. Pozice se
neotevírá za candle-close ani automaticky za midpoint. `market_stream._dispatch:84`
počítá midpoint, předá jej přes `_symbol_prices` do aktualizace pozic (`:137`).
Executor v `paper_trade_executor.py:2918` a `:2955` tento `current_price` použije
jako exit; také timeout používá poslední čerstvou scalar cenu (`:1350`).

Proto realizovaný gross:

- proti hypotetickému mid-to-mid pohybu obsahuje přibližně zápornou polovinu
  vstupního spreadu;
- proti realizovatelnému taker exitu je přibližně o polovinu výstupního spreadu
  optimističtější (BUY by se uzavíral na bid, SELL na ask);
- závisí na zvolených TP/SL/timeout a dynamických exitech. Nulový výsledek po této
  stop-time transformaci neříká, že cena neměla informaci na všech pevných horizontech.

Jde o potvrzenou asymetrii modelu, nikoli vyčíslenou závadu historického P/L.
Snapshot nemá entry/exit BBO ani quote ages, takže nelze odečíst přesnou chybu.
Konstantní 1 bp slippage je samostatný odečet; není doloženo, jak dobře kompenzuje
chybějící exit half-spread, latenci a hloubku knihy. Směr celkové chyby po této
kompenzaci nelze určit pouze z uložených cen. Náhodný sampling/missing quote může
přidat další zkreslení; jeho velikost zde `NOT_VERIFIED`.

Jednotky v `_calculate_pnl:1320–1345` jsou správné pro deklarovaný model:
`0.0008 × 10 000 = 8 bps` round-trip fee a `0.0001 × 10 000 = 1 bp` slippage.
`pnl_pct` jsou procentní body, proto další násobení 100 dává bps. Není správné
tyto dva konfigurační zlomky interpretovat jako 0,0008 % a 0,0001 %.
Default v executoru je ovšem 15+3 bps; 8+1 je scénář této evidence, ne univerzální default.

Oficiální tabulka Binance při auditu uvádí pro Regular User spot 0,100 % na stranu,
s BNB 0,075 %; orientační fee za vstup a výstup tedy 20 nebo 15 bps před dalším
slippage. To potvrzuje, že 8 bps celkových fees je pro tento retail spot scénář
optimistické. Skutečný účet, VIP tier, regionální sazbu a případné promo podmínky
audit neověřil. [Binance fee schedule](https://www.binance.com/en/fee/trading),
[Binance výpočet spot poplatků](https://www.binance.com/en-NG/support/faq/detail/e85d6e703b874674840122196b89780a).
PAPER SELL s obráceným cenovým P/L navíc není důkaz proveditelného spot shortu;
pro skutečný instrument by bylo třeba zahrnout jeho vlastní náklady a omezení.

Historické memo `RESEARCH_M5_COST_ARITHMETIC.md:28–30` používalo pro poplatky
neoficiální zdroje. Závěr o cenovém řádu lze nyní podpořit primárním zdrojem;
specifické tvrzení o nedosažitelnosti tieru pro konkrétní účet zůstává neověřené.
Nejde o návrh přepisovat dosavadní P/L nebo přepnout model uprostřed experimentu.

### A4. Závislost a intervaly

V celém snapshotu je **226 párů časově překrytých pozic**, ale **žádný pár na stejném
symbolu ani stejném kontextu**. Překryv zde tvoří různá aktiva. Sériová závislost
trhu i společné učící historie může existovat také bez překryvu držení pozic.
Znaménko a velikost kovariancí rozhodují, zda iid interval nejistotu podhodnotí;
automatické tvrzení o násobně příliš úzkém intervalu není doloženo.

Nezávislá citlivost: společný circular moving-day bootstrap obou ramen, seed
20261109, 5 000 replikací, 22 kalendářních dnů včetně dvou bez trades.
Kombinuje sumy/counts, tedy zachovává trade-weighted průměr:

| Délka bloku | 95% CI A−C (bps) | Bootstrap SD |
|---|---:|---:|
| 1 den | [−1,2015; +4,0841] | 1,3464 |
| 2 dny | [−0,7822; +3,4933] | 1,0941 |
| 3 dny | [−0,5456; +3,4855] | 1,0131 |
| 7 dnů | [−0,7666; +3,1664] | 1,0079 |

Všechny intervaly obsahují nulu. Zde jsou užší než z/Welch interval, nikoli širší.
Je to **citlivost popisu tohoto vzorku**, ne výběr nejpříznivějšího intervalu ani
důkaz nezávislosti. Jen 22 dnů, změny režimu, nepravidelné počty a circular spojení
konců limitují bootstrap; sedmidenní bloky poskytují velmi málo nezávislých úseků.
Denní bootstrap zachovává intradenní cross-symbol vazby, ale ne všechno přenášení
informace přes dny ani změny admission politiky. Budoucí protokol musí určit bloky
a minimální kalendářní dobu předem. Efektivní n nelze poctivě nahradit prostým 915.

### B5–B6. Předpoklady, testy a závěr o nemožnosti učení

**Aritmetika většiny deskriptivních metrik je správná; jejich logická interpretace ne.**

1. Kladný agregovaný gross není nutnou podmínkou zlepšení filtrem. Dvě stejně
   četné předem rozlišitelné skupiny s gross +20/−20 bps mají celkem nulu;
   výběr první má net +11 bps při nákladu 9. `extra_checks.py` tento kontrapříklad
   ověřuje. Je to logický příklad, nikoli nová obchodní strategie nebo tvrzení,
   že takové skupiny byly v CryptoMasteru nalezeny.
2. Homogenita průměrů kontextů je užitečná otázka, ale Q test zachází s odhadnutými
   rozptyly průměrů jako se známými. Při malých n a heteroskedasticitě nemá přesně
   χ² rozdělení. Wilson–Hilferty aproximace sama je zde velmi přesná: rozdíl p je
   jen 0,000873. Hlavní problém není WH, nýbrž distribuce statistiky pod nulou.
3. Korelace prvních/druhých polovin kontextů má smysl jako stabilita konkrétního
   členění. Poloviny však mají pro různé kontexty jiná kalendářní okna, odlišnou
   přesnost a byly vybrány podle konečného n≥20. Test nepostihuje stabilitu krátké
   paměti, prediktivní nelinearity ani kauzální přínos jiné informace.
4. Korelace odhadu s outcome je užitečná pro současné monotónní pravidlo.
   Hodnotí jen uskutečněné obchody, nikoli HOLD a kandidáty zablokované pozdějšími
   gates; pozitivní korelace není jedinou možnou podobou predikce. `UNINFORMATIVE`
   může navíc označit silně zápornou, a tedy informační, vazbu.
5. Rozdíl poslední a první čtvrtiny s podmínkou poslední>0 není statistický test
   zlepšování. Ignoruje nejistotu, dvě prostřední čtvrtiny a měnící se mix obchodů.

Reprodukce nulových simulací: stejný generátor jako `tests/test_learning_diagnostics.py:15`,
10 kontextů ×40, nezávislý Gaussian net N(−9,18²), nezávislý odhad N(−9,3²).

| Označení | 200 seedů 0–199 | 1 000 seedů 0–999 |
|---|---:|---:|
| CONTEXTS_DIFFER | 16/200 = 8 % | 80/1 000 = 8 % |
| CONTEXTS_PERSIST | 10/200 = 5 % | 43/1 000 = 4,3 % |
| ESTIMATE_RANKS_OUTCOMES | 5/200 = 2,5 % | 38/1 000 = 3,8 % |
| CURVE_IMPROVING | 77/200 = 38,5 % | 361/1 000 = 36,1 % |

Trojice 8/5/2,5 % v `LOGIC.md:245` je tedy reprodukovatelná, ale vynechává hlavní
slabinu křivky. Přibližná Monte Carlo chyba 8% četnosti při 1 000 opakováních
je 0,86 procentního bodu (jedna SE), takže nejde o kalibrovaný 5% test.
Původní automatický test používá jen seedy 100–199: výsledky 9/4/1 poplachů
a toleruje až 15/12/12 ze 100 (`test_learning_diagnostics.py:50–54`). To kontroluje
hrubé poruchy, nikoli deklarovanou hladinu. Na 10 000 dalších Gaussian simulacích
Q s přesným χ² tail dává při n=20/40/100 na kontext **9,36/6,81/5,77 %**;
WH dává téměř totožně **9,41/6,83/5,79 %**.

Kritická ρ `1,645/√(n−1)` odpovídá velkovýběrové jednostranné aproximaci kolem
nulové rank korelace. Pro malé k, ties a závislé kontexty to není přesný test.
Pozorované záporné hodnoty tím nezískají důkaz pozitivní persistence; p-hodnoty
a intervaly ale musí být kalibrovány pro zamýšlený design, ideálně blokově.

Simpsonovo zkreslení/nestacionarita jsou **PLAUSIBLE, nikoli prokázané vysvětlení**.
V datech například BULL/BEAR zároveň označuje trend BUY/SELL; ostatní zdroje jsou
SIDEWAYS. Regime, source a side proto nejsou nezávislé dimenze. Varianty V0/V5
a V3/V6 dávají stejné lifty: deset názvů není deset nezávislých replikací.
Žádný z uvedených rozborů neopravňuje tvrdit, že signály určitě edge mají.
Přesná formulace je: **dosavadní implementace a měření neprokázaly stabilní
prediktivní přínos; nulové či záporné průměry jsou důvodem pro další testovatelnou
hypotézu, nikoli matematickým zákazem podmíněného zlepšení.**

Historické cost-wall/long-horizon nálezy podporují opatrnost vůči konkrétním
testovaným konfiguracím. Jejich jiné horizonty, fill modely a náklady nejsou
univerzálním důkazem nemožnosti současného PAPER learneru. Funding carry memorandum
navíc samo uvádí jiný, předběžný lead a omezení 15 měsíčních bodů; není důvod
jej prezentovat jako nasazenou strategii nebo WR jednotlivých současných trades.

### C7–C9. Replay, live shoda, look-ahead a anti-persistence

Původní replay jsem nezávisle reprodukoval. Development=549, holdout=366,
vybrána V4_symbol_side, `HOLDOUT_LIFT_NOT_CONFIRMED`; všech deset holdout liftů záporných.

| Výpočet | Holdout n | Lift (bps) | Orientační 95% CI |
|---|---:|---:|---:|
| V0 původní | 366 | −3,5043 | [−7,5203; +0,5118] |
| V0 prior bez vlastního kontextu, stále globální prostý průměr | 366 | −3,5043 | [−7,5203; +0,5118] |
| V0 prior ostatních kontextů s EWMA | 366 | −3,5203 | [−7,5362; +0,4955] |
| Rekonstrukce live cohort/provenance/history pravidel | 366 | −3,4023 | [−7,4192; +0,6147] |
| Totéž, pouze native v holdoutu | 352 | −3,6688 | [−7,8155; +0,4779] |
| V0 pouze CONTROL holdout | 154 | −7,7069 | [−13,8440; −1,5697] |
| V0, výsledek po odečtení denního průměru | 366 | −3,3786 | [−7,3592; +0,6020] |
| V2 bez decay původní | 366 | −4,4114 | [−8,4179; −0,4048] |
| V2, odečtení denního průměru | 366 | −4,3669 | [−8,3373; −0,3965] |

Tyto citlivosti jsou **exploratorní**, nikoli další nezávislé potvrzující testy.
Znaménko tedy není vysvětleno jen vlastním kontextem v prioru, shodami mediánu,
jednoduchými denními offsety nebo samotným výběrem ADAPTIVE. Negativní výsledek
CONTROL podmnožiny je důvod zkoumat hypotézu, ne automaticky věřit anti-persistenci.
TP/SL geometrie a selekce kandidátů mohou ovlivnit rozdělení a časové vztahy;
bez historických BBO/candidate paths nelze izolovat jejich kauzální podíl.

Rozdíly oproti live jsou širší, než naznačuje jen poznámka o prioru:

- Live načítá source-specific posledních 500 closes, potom přijímá pouze shodný
  `policy_cohort` a ověřenou provenance; starší neoznačené výsledky nepoužívá.
- Prior je EWMA **ostatních kontextů stejné kohorty**, ne celého datasetu.
- Replay obsahuje všech 915 řádků, včetně 113 bez policy a 37 neural, a neodděluje
  cost/profile podpis ani neural bucket. Neprovádí warmup/probe/admission/risk/cap
  simulaci. Výsledek je rank diagnostika realizovaných outcomes.

Nezávislá rekonstrukce s historií dostupnou až k zaznamenanému `policy_last_close_ms`
vrátila **802/802 shodných odhadů, 802/802 počtů a 802/802 training hashes**.
Při použití všech closes až k entry místo k poslednímu skutečně načtenému close
byl rozdíl v jediném řádku (max 1,5708 bps, celková MAE 0,001959 bps).
Shoda zachyceného prefixu je důkaz konzistentní attribution, ne zlepšování profitability.

Časová podmínka `exit_ms <= entry_ms` v replayi pro běžné kladně dlouhé obchody
nepoužívá jejich budoucí výsledek. Souběžné dosud neuzavřené pozice se nezapočítají;
příslušný test v `test_learner_replay.py:33` prošel. U shodného timestampu ovšem není
definováno pořadí dostupnosti/commitu. Navíc `evaluate()` dovoluje nulovou délku
a samostatný trade `(entry=exit=1000, net=123)` dostane odhad **123 už sám ze sebe**.
Preregistrace nemá ani stejnou vstupní validaci jako evaluate: přijala zápornou
délku a 300 záznamů se stejným ID. CLI zápornou délku filtruje, ale nulovou délku
a duplicitní ID ne; nedostatky tedy nejsou všechny dosažitelné pouze přímým API.
Ve snapshotu je nulových/záporných délek 0 a duplicit 0: nevysvětlují jeho záporný lift.

Rozdělení podle mediánu je v nynějším V0/V2 holdoutu 183/183, 366 unikátních odhadů,
žádná shoda na mediánu. Obecně ale `e>median` vs `e<=median` může být nevyvážené;
obrácení znaménka při ties nemusí přesně obrátit lift. Medián z celého hodnoceného
okna používá budoucí distribuci odhadů k definici retrospektivních skupin.
To je přijatelné pro předem deklarovanou deskriptivní rank metriku, nikoli pro
simulaci okamžitého vstupního prahu, který by obchodník tehdy znal.

### C10–C11. Předregistrace a rozhodnutí o nasazení

Pozitivní stránka: dokument výslovně přiznává, že C1 vznikla po pohledu na stará
data a že tato data nesmějí sloužit jako důkaz. Kód při scoringu používá ostrou
podmínku `entry_ms > scored_after_ms`. Výsledek na tomto exportu je správně
`fresh_n=0`, `INSUFFICIENT_DATA`. Hypotéza C1 neobrací směr obchodu; obrací odhad,
podle kterého se pořadí kontextů hodnotí.

Nelze ověřit přesné nasazení cutoff souboru nebo že autor před jeho registrací
neviděl žádná nová data; commit `91363c5` má čas 07:33:21 UTC, dokumentovaný cutoff
07:31:56. Samotný rozdíl několika minut není důkaz nekorektního postupu.
Chybí ale nezměnitelný protocol/config/data manifest a přesné rozhodovací okno.

**Opakované pohledy:** timer spouští replay dvakrát denně, n≥300 je jen minimum,
`CONTRARIAN_NOT_SHOWN` sběr neuzavírá a LOOP při kterémkoli potvrzení nařizuje
implementaci. Tím 95% interval není testem s jednou deklarovanou chybovostí.
Ilustrativní nulová simulace 5 000 nezávislých dvouramenných experimentů s pohledy
při celkovém n=300,600,…,3000 dala první kladnou dolní mez ve **2,20 %**, ale
alespoň jednu kladnou dolní mez během celé série v **9,74 %**. Není to odhad
přesné chybovosti C1; ukazuje problém i bez tržní závislosti a modelového výběru.

**Síla testu:** pro dvě stejně velké poloviny s SD 18,912 bps je SE≈2σ/√N.
Při N=300 má 95% interval half-width≈4,28 bps; 80% síla s kritériem dolní
dvoustranné 95% meze>0 vyžaduje skutečný lift přibližně **6,12 bps**.
Pro lift 3,5 bps vychází přibližně **917**, pro 1,39 bps **5 812**, pro 5 bps
**450** celkových vzorků za iid předpokladu. Závislost, nevyváženost a více
kalendářních režimů mohou požadavek zvýšit. Tato čísla jsou plánovací aproximace,
nikoli návod dodatečně prodlužovat test, dokud vyjde požadované znaménko.

Změna na CONTROL=1 je rozumný krok pro lepší pozorovatelnost **admisibilních**
kandidátů. Současná změna limitů, cooldownu, symbolů a spodní net meze však mění
target population. Nová C1 může být korektně testována na této nové populaci,
pokud je její definice předem pevná; nelze efekt připsat samotnému learning mechanismu
srovnáním P/L před/po 07:31. Stará historie bez decay může dlouho dominovat novým
kontextům; nové symboly zároveň začínají na global prioru. Zahřívací pravidlo,
neural/native segmentace a použití staré historie musí být součástí protokolu.

Krok „potvrzeno → nový live learner“ je příliš přímý. Chybí:

- ošetření opakovaných testů a časové závislosti;
- minimální délka sběru a ověření nezměněné kohorty/configu;
- předem definovaná ekonomická velikost zlepšení a nezávislá dopředná replikace;
- přesný převod rank score na sigmoid/acceptance/sizing pravidlo a jeho očekávaný
  dopad na data volume; velikost pozic se kvůli skóre nemá automaticky měnit;
- validace pořadí eventů, duplicate IDs, holdout hranic a nespárovaných observations;
- samostatné experimentální review před změnou policy, i kdyby deploy testy byly zelené.

V PAPER není nutné čekat na důkaz reálné profitability, aby šel provést další
omezený experiment. Je však nutné novou fázi takto označit, zachovat sběrnou kontrolu
a nesdělovat „učení potvrzeno“ pouze z jednoho opakovaně sledovaného rank intervalu.

## 4. Proces agenta — odpovědi D12–D18

### D12. Autonomie a jednobodová selhání

Dokumenty shodně uvádějí `DECISION_READY` 28. 10. 17:47 a přechod S2 až 9. 11.
07:01:41: přibližně **11 dní 13 hodin** prodlevy. Údaj „12 dní“ je běžné zaokrouhlení.
Příčinou podle zápisů je uzavřené sezení; serverové logy této události nebyly součástí
nového přímého ověření.

Serverový eval oneshot+Persistent timer zlepšuje nezávislost výpočtů na sezení.
Ale `stage_step.sh` řeší pouze S2→S3, a tato etapa i timer jsou podle nové autorizace
zrušené. C1 implementace/notifikace jsou opět instrukcí v session LOOP.md.
Obnova session cronu po pěti dnech se provádí ze stejného cronu: když neběží nebo
vyprší, nemá kdo obnovu provést. Není doložen nezávislý delivery/heartbeat kanál.

Další mezery: jednotky nemají `OnFailure`, timer časy nemají explicitní `UTC`
(platí timezone serveru, zde neověřeno), replay failure nevrací neúspěch celého
run_eval, `next_action` není opatřeno experiment/config hashem a expirací.
Vypnutý stage timer není aktuální hrozba nového stopu; uvedené jsou latentní mezery,
které nesmí být znovu aktivovány omylem.

### D13. Změny během půlhodiny

Uložená posloupnost je: 07:01 S2 → 07:08 návrat S1 na pokyn operátora → 07:17
vyšší objem → 07:31 CONTROL=1 a C1. Změna cíle na sběr dat legitimizuje zrušení
omezení virtuálních ztrát; samotné obrácení předchozího rozhodnutí není pochybení.
Sekvence ale neumožňuje rozlišit efekt jednotlivých změn a nevytváří stabilní
novou kohortu pro kauzální srovnání se starou.

Lepší postup by byl zaznamenat nové rozhodnutí s okamžikem účinnosti, uzavřít
historické S1/S2 hodnocení, připravit jeden konzistentní config release, ověřit
jeho runtime identitu a až poté zahájit pevně definované měřicí okno.
Nečekat na zisk; čekat na stabilní konfiguraci, datovou kompletnost a předem
stanovený počet nezávislých kalendářních bloků. Změna během experimentu se zaznamená
jako nová kohorta nebo odchylka protokolu, nikoli jako „stejný experiment pokračuje“.

### D14. Review a kvalita testů

245 nyní povolených cílených testů prošlo. Uvedených 402 testů při předchozím
nasazení není tatáž sada; jeho konkrétní JUnit/source manifest není v zadání doložen,
proto počet 402 zde znovu nepotvrzuji. Počet testů není důkaz pokrytí statistického
protokolu ani chybových větví shellového deploymentu.

Přísný požadavek `CLAUDE.md` na všech osm agentových schválení je pro každou
kosmetickou PAPER změnu nepřiměřený. Jediný autor + dobré testy může stačit na
malou opravu reportu. Změna estimandu, trial policy, timeru nebo deploymentu však
potřebuje alespoň jedno nezávislé, konkrétní review přesného diffu/manifesta a
jeho selhání. Statistický reviewer a runtime reviewer řeší různé otázky; jejich
počet lze přizpůsobit rozsahu. Stávající pravidlo je třeba výslovně nahradit,
ne mlčky ignorovat.

Historické reporty 54–56 naopak obsahují nezávislá schválení a mutation/rollback
testy. Není spravedlivé připsat celé historii pouze self-review. Pro 9. 11. chybí
srovnatelně dohledatelná attestation; skutečná absence review zůstává `NOT_VERIFIED`.

### D15. Nasazení a drift

Souborové nasazení může být reprodukovatelné i bez čistého Git HEAD, pokud má
úplný content manifest a dependency/config lock. Říjnové reporty takové SHA
manifesty popisují. Nové `deploy_bot_files.sh` a `deploy_probe_volume.sh` ale
nemají očekávané předchozí hash hodnoty, výsledný úplný release manifest,
vzájemný lock ani vazbu na ručně kopírovaný `/opt/cryptomaster_research/code`.
Generic helper přijímá libovolné FILES/VARS; komentář o neměnění TP/SL a costs
není enforceovaný allowlist. Neprokazuje to, že taková zakázaná změna proběhla.

`set -e` není transakční rollback: při selhání druhého `install`, zápisu konfigurace
nebo `daemon-reload` po prvním přepsaném souboru se explicitní rollback nevolá.
Restart recovery pak může načíst smíšený release. Backup sám tuto situaci neřeší.
Nulový počet pozic je pouze okamžitý snapshot; mezi kontrolou a restartem může
entry scheduler otevřít další. Chybí zastavení přijímání vstupů a ověření stavu
v kritické sekci. Rollback navíc po 90 sekundách jen loguje active stav a nemá
stejně silné ověření obnovených hashů/READY/PAPER invariantů jako původní forward deploy.

Výzkumný run používá složku pouze podle data, tedy ráno i večer stejné soubory
přepíše. `latest` se přepne před dokončením replaye a obě části čtou živou DB
nezávisle; mohou reprezentovat různé počty řádků. Při chybě replaye je možné mít
nový report se starým replayem. Bez snapshot ID/source SHA není jednoduché
zrekonstruovat přesně to, co agent při rozhodnutí viděl.

### D16–D17. Dokumentace, autorita a komunikace

Konkrétní rozpory či zastarávání:

| Místo | Rozpor / omezení |
|---|---|
| `AGENTS.md` vs `autonomy/LOOP.md:19,27` | Audit zakazuje SSH/deploy/commit; LOOP nařizuje deploy/commit/push. Úkolově omezená pravidla je nutné označit, ne považovat vše za současně platné. Přímý pozdější pokyn operátora může obecné omezení přebít; úplná autorizace zde není k dispozici. |
| `CLAUDE.md` CORE ARCHITECTURE | RDE/trade_executor/Redis jako hlavní popis neodpovídá nynější doložené PAPER source-learning cestě. |
| `CLAUDE.md` autonomous loop | Opravy/auto-deploy až do WR>50/P&L>0 a 30min cykly neodpovídají novému MAX_DATA experimentu. |
| `.maestro.md:179` | „real-money trading context“ je historická šablona; tento audit je výslovně PAPER a ztráta je povolený výzkumný náklad. |
| `LOGIC.md:90` vs `:216` | Starý text říká, že net predikce má zero floor; novější probe profil zachovává znaménko. Chybí jednoznačné verzování staré věty. |
| `LOGIC.md:235` a `:249–251` | Kohorta pokračuje i po změně populace, a „všichni kandidáti“ přehlíží budget/risk selekci. |
| Report 58 `:68`, S2 zápis `:17` | Stále uvádí další S3 a termín 30. 11.; autonomní dokument a state už S2/S3 ruší. Historický záznam potřebuje označení superseded. |
| Předregistrace `:36` | „Kontrarián nevytvoří hrubý edge“ je opět příliš kategorické; výběr může změnit podmíněný gross, což zatím není prokázáno. |
| `LOOP.md:23` vs `run_eval.sh:79–81` | LOOP mluví o běžném HOLDOUT verdictu na datech po prereg_after; skript běžný replay stále počítá z celé epochy, pouze zvláštní prereg objekt je fresh-only. |
| `learner_replay_report.py:60–73` | Markdown nezobrazuje `preregistered` výsledek ani cutoff; ty jsou jen v JSON a stdout. Čtenář replay.md může zaměnit starý holdout za nový test. |

Silné formulace „přesně nula“, „nemá žádnou předpovědní hodnotu“, „další ladění
cíl nepřinese“ překračují data. Naopak reporty 54–57 správně oddělují mechanickou
funkčnost od edge a uvádějí neověřené skutečnosti. Nová diagnostika by měla používat
např. `POSITIVE_GROSS_NOT_SHOWN`, `CONTEXT_DIFFERENCE_NOT_SHOWN`,
`POSITIVE_PERSISTENCE_NOT_SHOWN` a `POSITIVE_RANKING_NOT_SHOWN` s n/CI/cohort,
nikoli kategorické ontologické soudy. To je návrh, kód nebyl upraven.

### D18. Soulad s cílem operátora

Vyšší PAPER objem, odstranění adaptivního odhazování pro období sběru a logování
odhadů jsou smysluplné pro cíl „více dat a vysvětlení učení“. Dosažená virtuální
ztráta sama není chyba, porušení bezpečnosti ani automatický důvod ke stopu.
Podstatné metriky mají být informační: pokrytí kandidátů/kontextů, kvalita attribution,
kalibrace na dosud neviděných datech a dopředný rozdíl zvolených politik.

Dnes převládá počet uzavřených trades, nikoli funnel od kandidátů k admissions,
který by vysvětlil, proč se sbírá málo nebo proč je jiná populace. Více vzájemně
závislých obchodů nemusí přinést stejně velký informační zisk. Ani „všichni vstoupí“
neruší cap/quote/data limity. U Stonkfly je navíc třeba počítat počet **uzavřených
obchodů s využitým, proměnlivým kontextem**, nikoli počet neuronových inference;
37 realizovaných neural outcomes bez CONTROL nestačí k tvrzení o jeho přínosu.

## 5. Doporučení pro proces — podle přínosu

Jde o návrhy pro další samostatně autorizované zadání. V tomto auditu se nic
z následujícího neimplementuje. Sloupec skill je mapování použité diagnostické
metody, nikoli požadavek na další daemon nebo povinnou sadu agentů.

| Priorita | Konkrétní pravidlo | Kdy pokračovat / čekat / review | Ověřovací test | Skill |
|---|---|---|---|---|
| 1 | Oddělit trvalý sběr a evaluaci od session lifecycle; přidat externě ověřitelný heartbeat, stav posledního úspěchu a failure alert. | Sběr běží i bez sezení; při nedoručeném heartbeat se opravuje provoz, nedeklaruje learning výsledek. | Zavřít klienta, vynechat timer běh, rozbít replay; detekce a alert dorazí bez session cronu. | `/fortify` |
| 2 | Před C1 rozhodnutím uzamknout experiment ID, cutoff, config/source/dataset SHA, primární estimand a konec testu. | Čekat na předem určené okno a úplnost; změnu pravidel musí zkontrolovat nezávislý reviewer, změnu cíle operátor. | Změna configu/policy hash uprostřed sběru nevstoupí tiše do původní kohorty. | `/calibrate` |
| 3 | Nasazovat konkrétní neměnný artefakt se scope allowlistem, preimage/postimage SHA a jediným lockem; zahrnout výzkumný reportový kód. | Běžné povolené PAPER kroky bez opakovaného souhlasu; review při změně policy/executor/deploy/protokolu. | Chyba každého install/write/reload/SIGTERM kroku obnoví celý manifest a ověří runtime; drift blokuje deploy. | `/fortify` |
| 4 | Přechod configu provádět s quiescence vstupů, dokončením/recovery pozic a kontrolou skutečného env po startu. | Čekat na doložený bezpečný přechod, ne na P/L. | Kandidát vzniklý mezi kontrolou n=0 a restartem neobejde admission barrier; restart loop nesplní health check. | `/fortify` |
| 5 | Review vázat na přesný artefakt a riziko. Statistický protokol kontrolovat odděleně od Python correctness. | Jeden nezávislý reviewer pro změnu experimentu; širší review jen pokud se mění execution/persistence. | Reviewerův manifest se neshoduje s nasazovaným → nasazení zablokováno. | `/guard` |
| 6 | Každé měření ukládat pod jedinečným UTC run ID, společný read-only datový snapshot pro report i replay, společný completion manifest. | `latest` až po úspěchu celého běhu; selhání replaye je failure, ne čerstvý kombinovaný výsledek. | Ranní a večerní běh zachovají oba artefakty; crash mezi report/replay nepublikuje smíšenou sadu. | `/fortify` |
| 7 | Jeden aktuální index autority: cíl, povolené akce, aktivní experiment, superseded dokumenty a seznam výjimek s důvodem/časem. | Operátora žádat při nové hypotéze/změně cíle nebo risk scope, nikoli pro každý autorizovaný read/test. | Kontrola dokumentů odhalí aktivní instrukci S3 při MAX_DATA, neaktuální policy a konflikt audit/deploy scope. | `/streamline` |
| 8 | Zpráva vždy uvádí snapshot, cutoff, n, kalendářní pokrytí, effect/CI, status a co bylo NOT_VERIFIED. | Bez inference proof psát „neprokázáno“; bez aktuálního serverového důkazu nepsat „nasazeno a healthy“. | Golden report s nulovou podmíněnou i nepodmíněnou evidencí neprodukuje kategorické „nemůže fungovat“. | `/refine` |

Orientační skóre procesu podle `diagnose` (subjektivní auditní škála, nikoli
statistická metrika modelu):

| Dimenze | Skóre | Důvod |
|---|---:|---|
| Kvalita zadání | 3/5 | Aktuální audit přesný, ale rozpory mezi trvalými návody a etapami. |
| Správa kontextu | 2/5 | Mnoho verzovaných zápisů bez jednoho aktuálního provozního zdroje pravdy. |
| Nástroje | 3/5 | Read-only evaluace a cílené testy dobré; rollback/error propagation slabší. Nehodnocen počet globálních nástrojů IDE. |
| Architektura procesu | 2/5 | Serverový výpočet oddělen, ale rozhodnutí a alert zůstávají závislé na sezení. |
| Spolehlivost a validace | 3/5 | Výborná rekonstruovatelná attribution, chybí přísnější experimentální a deployment failure testy. |
| Celkem | 13/25 | Prioritou je `/fortify` a `/calibrate`, nikoli další trading rewrite. |

## 6. Doporučení pro měření a učení

| Co změnit | Jaký test by změnu ověřil | Co zachovat / skill |
|---|---|---|
| Rozdělit „ranking“, „policy selection effect“, „portfolio P/L“ a „data yield“ na různé estimandy. | Dataset s lepším průměrem přijatých trades, ale menším total P/L nesmí vykázat oba výsledky jako improvement. | Post-cost jednotky, původní P/L; `/calibrate`. |
| Preregistraci doplnit pevným N+kalendářní dobou, nebo validním sekvenčním pravidlem; zamknout minimální významný efekt. | Null simulace se stejným plánem pohledů, blocks/ties a výběrem variant drží předem zvolenou celkovou chybovost. | Čerstvý cutoff, stará data jen trénink; `/guard`. |
| C1 nejprve hodnotit jako novou forward hypotézu; pro změnu live acceptance předem definovat přesný mapping a druhou nezávislou replikační fázi. | Replay rank výhra sama nevyvolá promotion; policy test měří i acceptance rate/candidate throughput a drží kontrolu. | PAPER, jedno runtime a centrální risk; `/guard`. |
| V0 replay sjednotit s čistým live decide nebo jej přejmenovat na approximation; oddělit neural/native i source/profile podpisy. | Pro 802 tagovaných řádků zrekonstruuje přesné n/mean/training hash; žádný jiný cohort či future close jej nezmění. | Chronologický replay a determinismus; `/calibrate`. |
| Validovat unikátní IDs, kladnou délku, finite data a event availability také v prereg API. | Nulová/záporná délka, duplicitní ID a self-outcome leak fail-closed; legitimní souběžné pozice čekají na dostupný close. | Read-only vstup a žádná oprava historických dat; `/guard`. |
| Oddělit nové MAX_DATA kohorty a nezávisle vykazovat staré A/C; neporovnávat dnešní CONTROL se zmrazeným historickým ADAPTIVE jako současný experiment. | Po CONTROL=1 je current-cohort A/C nedostatečné, starý výsledek označen HISTORICAL. | Warmup/probe samostatně; `/calibrate`. |
| Ke kandidátům lokálně a bounded logovat eligibility, rejection důvod, context, prior/estimate, všechny admission probabilities, final gate a ID dostupného outcome. | Součet admitted/held/risk/quote/budget rejects se rovná počtu deduplikovaných kandidátů; výpadek telemetry je viditelný. | Existující quota/outbox, žádné per-neuron/per-tick cloud zápisy; `/fortify`. |
| Kvalitu signálu hodnotit také na pevných horizontech a BBO, nejen na stop-time exit P/L; odlišit fill cost od čisté predikce. | Konstatní mid s nenulovým spreadem dá očekávanou entry/exit friction; symetrické BUY/SELL mají symetrický náklad. | Primární 9bps historický scénář neměnit; stress scénáře odděleně; `/guard`. |
| Nahradit kategorické diagnostické kódy opatrnými názvy; křivku ponechat jako popis nebo zavést předem testovaný trend. | Nulové simulace zahrnou CURVE; pozitivní podmíněný edge při nulovém agregátu nesmí být označen za nemožnost učení. | Pearson/Spearman, sample SD a explicitní malé n; `/refine`. |
| Homogenitu a stabilitu ověřovat pro heteroskedasticitu a blokovou závislost; předem zvolit robustní/permutation postup a vykazovat power. | Simulace null i struktury s malým n, unequal variance, ties a tržními bloky; kontrola nominální hladiny včetně MC intervalu. | WH může zůstat označenou aproximací pro diagnostiku, ne deployment gate; `/guard`. |
| Pro Stonkfly měřit dostupnost/variabilitu bucketu a inkrementální přínos proti native na srovnatelných BTC kandidátech. | Konstantní neural bucket nesmí vytvořit domnělý neural learning lift; frozen/plastic a missing-context zůstávají oddělené. | Žádný přímý Stonkfly executor, žádný připsaný cizí reward; `/guard`. |

Cílem není přidávat více hypotéz podle každého reportu. Preferuji jeden pevný
experiment se spolehlivou telemetry a nezávislým rozhodnutím před další změnou.
Zachovat read-only exporty, neupravovat outcomes, neresetovat historii ani P/L,
neoptimalizovat na témže holdoutu a nesnižovat transparentně započtené costs jen
proto, aby metrika zlepšení vyšla kladně.

## 7. Otevřené otázky pro operátora

Tyto otázky neblokovaly audit; jsou vstupem pro případné další implementační zadání.

1. Má být hlavním výsledkem lepší net na obchod, menší ztráta za hodinu, nebo
   více kvalitně atribuovaných vzorků? Jaký minimální lift stojí za snížení objemu sběru?
2. Je C1 míněna jako jednorázový test s pevným koncem, nebo sekvenční experiment?
   Jaká celková chybovost a jak dlouhé kalendářní pokrytí jsou přijatelné?
3. Smí agent po potvrzení pouze zahájit omezenou replikační PAPER fázi, nebo
   automaticky přepnout hlavní admission policy? Kdo schvaluje změnu protokolu?
4. Kdo nezávisle dostane alert, když session i timer mlčí, a kdo ověří doručení?
5. Který manifest je autoritativní pro bot, research kopii a efektivní config?
   Jsou dostupné přesné review/JUnit/deploy artefakty změn z 9. 11.?
6. Má se zachovat 9bps scénář jako primární měřítko učení a realistické fees/fills
   vykazovat zvlášť? Jaký konkrétní instrument a účet by případná budoucí ekonomická
   interpretace reprezentovala? Tato otázka neautorizuje REAL trading.
7. Jaký rozpočet CPU, disk a Firebase telemetry je přijatelný při 480 trades/den,
   aby sběr nezhoršoval completeness a spolehlivost bota?

## 8. Reprodukce, testy a hranice auditu

Spuštěno z lokálního repozitáře, bez SSH/deploy/commit/push:

```text
rtk python -B scripts/research/p0_8_plus_epoch_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json --out _workspace/external_audit_20261109/epoch
rtk python -B scripts/research/learner_replay_report.py --json docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json --prereg-after 1794209516 --out _workspace/external_audit_20261109/replay
rtk python -B -X utf8 _workspace/external_audit_20261109/recalculate.py
rtk python -B -X utf8 _workspace/external_audit_20261109/extra_checks.py
rtk python _workspace/code_audit_20260921_runner.py tests/test_learning_experiment_verdict.py tests/test_learning_diagnostics.py tests/test_learner_replay.py tests/test_paper_probe_limits_env.py tests/test_p0_8_plus_epoch_report.py tests/test_paper_source_learning.py tests/test_paper_learning_budget.py -q --tb=short
rtk python -B _workspace/external_audit_20261109/audit_integrity.py check
```

Testy proběhly v disposable code-only kopii s blokovanými externími síťovými
spojeními, bez kopírování runtime DB: **245 PASS / 0 FAIL / 0 SKIP**, 13,42 s.
JUnit: `_workspace/code_audit_20260921_k84h54n3_results.xml`.
Použity již instalované Python, NumPy a SciPy, bez přidání závislostí.
Nezávislá kontrola SciPy se týká výpočtů, nikoli volání brokeru nebo training runtime.

Artefakty:

- `external_audit_20261109/independent_results.json`: všechny přepočty, bootstrap,
  citlivosti replaye, Monte Carlo a plánovací power.
- `external_audit_20261109/extra_results.json`: přesné rekonstruované historie,
  původních 200 nulových simulací a minimální kontrapříklady.
- `external_audit_20261109/epoch/report.{json,md}` a `replay/replay.{json,md}`:
  nezměněné původní reportové nástroje nad snapshotem.
- `external_audit_20261109/integrity_before.json` a `integrity_after.json`:
  SHA kontrola 609 source/doc/test/evidence souborů včetně šesti chráněných runtime cest.

**NOT_RUN:** serverové kontroly, skutečné fault injection do deploy skriptů,
celá historická test suite, nové market fetches, měření resource/quota po 07:17,
fresh C1 vyhodnocení, implementace navrhovaných oprav.
Provozní shell mezery byly posouzeny staticky; uvedené fault testy jsou návrhy,
nikoli vykázané úspěšně provedené simulace. Globální Git status zůstává záměrně
dirty, se staršími změnami; audit nezahazoval soubory ani nepřepisoval minulou práci.

Všechny produkční zdroje, pravidla projektu, testy, evidence exporty a kontrolované
runtime soubory zůstaly beze změny. Nové jsou pouze tento auditní report, jeho
lokální pomocné výpočty/výstupy a JUnit artefakt. Audit nepotvrzuje dosažení WR>50,
kladného P/L ani aktuální bezpečnost celého vzdáleného serveru.
