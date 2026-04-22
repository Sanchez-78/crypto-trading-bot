# Claude Code Prompt — CryptoMaster Android App (CZ, full-preserved, optimized, production-ready)

## ROLE
Jsi senior Android developer, senior UX/UI designer a produktový architekt se silným citem pro moderní trading dashboardy.

Navrhni a implementuj **produkční Android aplikaci** pro existující trading bot projekt umístěný v:

`C:\Projects\CryptoMaster_srv`

Aplikace musí být:
- nativní Android
- Kotlin
- Jetpack Compose
- Material 3
- MVVM + clean architecture
- Coroutines + Flow
- Repository pattern
- Room cache
- Firebase / Firestore integrace, pokud ji bot reálně používá
- případně lehká REST/WebSocket vrstva, pokud je to efektivnější než přímé čtení

Nejde o demo.
Jde o **reálnou operační mobilní aplikaci** pro každodenní monitoring a kontrolu live trading bota.

---

## HLAVNÍ CÍL
Vytvoř Android aplikaci, která zobrazí:
- všechny důležité metriky trading bota
- historii obchodů
- otevřené pozice
- výkon dle coinů / symbolů
- výkon dle režimů trhu
- learning/model metriky
- health / diagnostiku / varování
- live signály a doporučení pro jednotlivé měny
- stav databáze a živosti systému
- přínosné grafy vývoje výkonu, učení a trhu
- moderní profesionální design odpovídající prémiové trading aplikaci

Aplikace musí fungovat jako **hlavní mobilní operační konzole** pro bota a zároveň musí vizuálně působit jako moderní profesionální produkt, ne jako interní prototyp.

---

## ZÁSADA TÉTO VERZE
Tato verze je **optimalizovaná bez ztráty obsahu**.

To znamená:
- zachovej všechny důležité požadavky z původního zadání
- nic podstatného nevyhazuj
- deduplikuj formulace
- sjednoť logiku
- zkrať opakování
- zachovej plný rozsah funkcí, metrik, grafů, explainability, designu i backend doporučení
- pokud narazíš na dvě podobné instrukce, slouč je do jedné silnější, ne slabší
- cílem je vyšší srozumitelnost a nižší tokenová zátěž, **ne omezení scope**

---

## GLOBÁLNÍ POVINNÁ PRAVIDLA
Tato pravidla platí **pro celou aplikaci**, není nutné je znovu opakovat v každé sekci:

### Jazyk
- vše musí být **česky**
- všechny názvy, texty, popisy, menu, tooltipy, chyby, stavy, filtry, tlačítka, grafy, sekce, dialogy, explainery, loading/empty/error stavy

### Timestampy a čerstvost dat
- každá důležitá položka musí mít timestamp
- vždy zobraz:
  - absolutní čas
  - relativní stáří typu „před 12 s“
  - indikaci čerstvosti dat
- platí pro:
  - KPI
  - signály
  - ceny
  - pozice
  - obchodní historii
  - grafy
  - learning metriky
  - health stav
  - warnings
  - symbol statistiky
  - agregace
  - snapshoty
- hranice čerstvosti přizpůsob reálné frekvenci update bota, orientačně:
  - čerstvá data: do 15 s
  - mírně stará: 15–60 s
  - podezřele stará: 1–5 min
  - kriticky stará: nad 5 min

### Kontextové vysvětlení / info menu
- u každé důležité položky, metriky, grafu, karty, sekce a varování přidej kontextové menu
- zobrazitelné přes ikonu `i`, dlouhé podržení, overflow menu nebo bottom sheet
- vysvětlení musí říct:
  - co položka znamená
  - proč je důležitá
  - jak ji interpretovat
  - co je dobrá / špatná hodnota
  - z jakých dat vzniká
  - k jakému timestampu se vztahuje
- vysvětlení nesmí být generické; musí odpovídat reálné logice trading bota

### Grafy
- přidej grafy jen tam, kde mají skutečný rozhodovací přínos
- ne dekorace
- každý graf musí mít:
  - název
  - jasný účel
  - období / rozsah dat
  - timestamp / informaci o čerstvosti dat
  - kontextové vysvětlení
- preferuj méně grafů s vysokou hodnotou před mnoha slabými grafy

### Moderní design
- moderní design není doplněk, ale povinná součást celého návrhu
- aplikace musí vypadat jako prémiový mobilní trading dashboard pro rok 2026
- dark mode ber jako primární vizuální směr, light mode jako sekundární
- design musí být čistý, profesionální, kompaktní a velmi dobře čitelný
- preferuj informačně bohaté, ale přehledné karty
- používej status badgy, chips, mini trendy, sparkline tam, kde dávají smysl, a jasnou vizuální hierarchii
- důležitější než dekorace je rychlá orientace v datech
- u každé sekce navrhni i vizuální kompozici, ne jen seznam dat

### Produkční mindset
- žádné placeholder bláboly
- maximálně využij reálná data z existujícího projektu
- preferuj produkčně použitelné řešení
- transparentně označ věci, které nešlo ověřit
- neprojektuj zbytečně složitou architekturu, pokud nepřináší užitek
- optimalizuj výkon, čtení dat a údržbu

---

## POVINNÉ UŽIVATELSKÉ POŽADAVKY
Uživatel explicitně požaduje:

### Dashboard
Musí obsahovat minimálně:
- počet obchodů
- úspěšnost
- poslední obchod
- otevřené pozice
- statistiky dle obchodovaných měn

### Obchody
- historie obchodů
- řazení dle timestamp
- každá karta obchodu musí obsahovat všechny dostupné detaily

### Signály na Dashboardu
- pokud bot generuje signály, dashboard musí obsahovat i **karty pro jednotlivé měny**
- každá karta musí ukázat doporučení typu:
  - Koupit
  - Prodat
  - Vyčkat
  - Slabý signál
  - Zablokováno
- zobraz i sílu signálu, režim, confidence a důvod rozhodnutí, pokud data existují

### Design
- zakomponuj moderní design přímo do celé aplikace, ne jako oddělený dodatek

---

## NEJDŘÍV ANALÝZA EXISTUJÍCÍHO BOTU
Nezačínej fiktivním modelem.
Nejdřív analyzuj skutečný Python projekt v `C:\Projects\CryptoMaster_srv`.

### Minimálně projdi:
- `main.py`
- `src/services/firebase_client.py`
- `src/services/trade_executor.py`
- `src/services/realtime_decision_engine.py`
- `src/services/learning_monitor.py`
- `src/services/risk_engine.py`
- `src/services/execution.py`
- `src/services/feature_weights.py`
- další soubory, které zapisují:
  - trades
  - metrics
  - model_state
  - signals
  - portfolio
  - advice
  - weights
  - health
  - compressed collections
  - snapshots

### Zjisti:
1. jaké datové zdroje skutečně existují
2. jaké Firestore kolekce existují
3. jaké dokumenty a pole se zapisují
4. jaké timestampy a formáty se používají
5. jaká data jsou live
6. která data je lepší agregovat v appce a která na backendu
7. jak omezit Firestore reads
8. jak navrhnout appku tak, aby byla rychlá, levná a stabilní
9. jaké signály a rozhodovací hodnoty bot generuje
10. které metriky už existují a které je nutné dopočítávat

### Vytvoř interní mapu schématu
Udělěj stručnou mapu:
- kolekce
- dokument
- klíčová pole
- periodicita update
- důležitost
- live / snapshot / cache vhodnost
- zda pole už má timestamp
- zda je vhodné pro graf
- zda je vhodné pro dashboard kartu

Nevymýšlej pole, pokud nejsou potřeba.
Pokud něco chybí, navrhni **minimální rozšíření backendu**.

---

# PRODUKTOVÝ NÁVRH — FINÁLNÍ ROZSAH APLIKACE

## NAVRHOVANÁ NAVIGACE
Použij spodní navigaci nebo taby s těmito sekcemi:

1. **Přehled**
2. **Obchody**
3. **Pozice**
4. **Výkon**
5. **Learning**
6. **Zdraví**
7. **Nastavení**

Struktura musí být jednoduchá, ale profesionální.
V případě potřeby přidej hlubší detail screens bez rozbití jednoduché hlavní navigace.

---

## 1. PŘEHLED
Účel:
během 3–5 sekund pochopit, zda bot běží správně, obchoduje, učí se a není v problému.

### Povinné bloky:
- stav bota: ŽIVÝ / ZPOŽDĚNÝ / OFFLINE
- poslední heartbeat
- poslední update
- počet obchodů celkem
- win rate / úspěšnost
- realizovaný PnL
- nerealizovaný PnL
- equity
- drawdown
- počet otevřených pozic
- celková expozice
- poslední obchod
- top symboly
- nejhorší symboly
- stručné shrnutí režimů
- learning health
- databázový / sync stav
- warning panel
- live signálové karty dle symbolů

### Signálové karty dle symbolů
Každá karta měny/symbolu může obsahovat:
- symbol
- poslední cenu
- doporučení: Koupit / Prodat / Vyčkat / Slabý signál / Blokováno
- sílu signálu
- confidence
- EV
- score
- weighted score
- režim
- aktivní feature flags
- spread
- timing info
- důvod zamítnutí nebo důvod TAKE
- timestamp signálu
- timestamp posledního updatu ceny
- barevný stav čerstvosti dat

Pokud je doporučení blokováno, ukaž i proč:
- vysoký spread
- slabé EV
- cooldown
- risk guard
- max positions
- timing
- pair block
- dead regime
- stale signal
- jiný reálný důvod z kódu

### Doporučené grafy v Přehledu
- equity curve
- pnl trend za 24h / 7d
- úspěšnost za posledních N obchodů
- win/loss strip posledních obchodů
- exposure split long/short
- open positions distribution
- rychlý trend stavu learning health
- rychlý trend signálové aktivity

---

## 2. OBCHODY
Účel:
kompletní audit obchodní historie.

### Požadavky:
- řazení dle timestamp DESC
- lazy loading / paging
- filtry:
  - symbol
  - směr
  - výsledek
  - režim
  - datum
  - exit reason
- vyhledávání
- pull to refresh

### Každá karta obchodu musí zobrazit všechny dostupné detaily, např.:
- symbol
- side / direction
- režim
- strategie / pattern / tag
- open time
- close time
- duration
- entry
- exit
- velikost
- leverage
- pnl absolutní
- pnl %
- fees
- důvod uzavření
- rr
- EV
- score
- weighted score
- confidence / probability
- feature flags
- SL / TP
- coherence
- execution quality
- trade id
- source signal id
- debug metadata
- timestamp vytvoření / uzavření / poslední aktualizace

### Detail obchodu
Musí obsahovat:
- všechny formátované hodnoty
- raw JSON/debug sekci ve sbalitelném bloku
- časovou osu obchodu
- rozhodovací kontext, pokud existuje

### Grafy v sekci Obchody
- distribuce výsledků obchodů
- pnl histogram
- délka obchodů
- win rate podle symbolu
- win rate podle režimu
- exit reason breakdown
- timeout dominance trend, pokud je to relevantní

---

## 3. POZICE
Účel:
live přehled o aktuálním riziku a otevřených obchodech.

### Zobraz:
- otevřené pozice
- symbol
- side
- entry
- mark price
- live pnl
- pnl %
- size
- leverage
- liquidation price, pokud existuje
- stop loss
- take profit
- trailing stav
- partial TP stav
- čas v pozici
- režim
- risk share
- exposure share
- timestamp poslední aktualizace

### Souhrn nad seznamem:
- total open positions
- total notional
- long/short exposure
- risk concentration
- same-direction concentration
- regime concentration
- stale position data warning

### Grafy v Pozicích
- exposure long vs short
- notional per symbol
- live pnl per position
- concentration heat summary

---

## 4. VÝKON
Účel:
pochopit, na čem bot vydělává a na čem selhává.

### Sekce:
- výkon podle symbolu
- výkon podle symbol+režim
- výkon podle režimu
- top/worst symboly
- top/worst režimy
- rolling performance
- expectancy
- profit factor
- avg win / avg loss
- recovery factor, pokud jde rozumně spočítat

### Každá výkonnostní karta/tabulka:
- symbol / režim
- trade count
- win rate
- pnl
- avg pnl
- EV
- convergence
- bandit score
- last trade time
- health status
- timestamp poslední agregace

### Grafy ve Výkonu
- pnl podle symbolu
- win rate podle symbolu
- pnl podle režimu
- trade count podle symbolu
- rolling EV
- rolling win rate
- rolling expectancy
- equity by period
- cumulative pnl

---

## 5. LEARNING
Účel:
monitoring adaptivní části systému.

### Zobraz:
- per regime stats
- per symbol-regime stats
- feature win rates
- feature importance / weights
- model health
- convergence
- bandit / policy hodnoty
- exploration vs exploitation, pokud existuje
- decision threshold summaries
- streak penalties
- velocity penalties
- execution quality summary
- risk budget state

### Grafy v Learning
- vývoj EV v čase
- vývoj convergence
- vývoj bandit score
- feature win rates trend
- feature weight trend
- learning health trend
- signal-to-trade conversion trend
- quality score trend
- drawdown vs policy response trend

### Kontextové vysvětlení zde musí být velmi kvalitní
Uživatel musí pochopit, co znamená:
- EV
- convergence
- bandit
- policy multiplier
- execution quality
- risk budget
- weighted score
- feature win rate
- symbol-regime performance

---

## 6. ZDRAVÍ
Účel:
rychle zjistit, proč bot může stagnovat nebo degradovat.

### Povinné položky:
- poslední heartbeat
- stall detection
- data freshness
- poslední signal time
- poslední decision time
- poslední trade time
- Firebase konektivita
- DB sync status
- poslední chyba
- deadlock / no-signal warning
- timeout dominance warning
- high spread warning
- stale metrics warning
- risk halt
- drawdown halt
- reconnect stav
- background sync errors

### Warning center
Rozděl na:
- INFO
- VAROVÁNÍ
- KRITICKÉ

Každé varování musí mít:
- název
- význam
- dopad
- od kdy trvá
- timestamp
- doporučenou akci

### Grafy v Zdraví
- heartbeat intervals
- stale update trend
- signal frequency trend
- trade frequency trend
- warning frequency
- timeout share trend
- DB error trend, pokud lze zjistit

---

## 7. NASTAVENÍ
Nezahlcuj.
Jen užitečné věci:
- interval obnovy
- auto refresh zap/vyp
- preferované období grafů
- výchozí filtry
- tmavý/světlý režim
- debug sekce
- zobrazení raw dat
- vypnutí náročných live grafů
- stav cache
- poslední synchronizace
- about / verze aplikace / verze datového schématu

---

# UX / UI A INTEGROVANÝ MODERNÍ DESIGN SYSTÉM

## Integrovaný designový cíl
Design musí být promítnutý do celé aplikace:
- navigace
- dashboard kompozice
- KPI karty
- signálové karty
- grafy
- seznamy obchodů
- detail obchodu
- warning centrum
- loading/empty/error stavy
- info dialogy
- timestamp prvky
- stavy datové čerstvosti

Nechci oddělený „design návrh“ bez dopadu na implementaci.
Chci, aby design byl zakomponovaný přímo do architektury komponent a obrazovek.

## Design
Aplikace musí působit jako moderní trading ops dashboard a zároveň jako vizuálně dotažený prémiový produkt:
- moderní, čistý, profesionální vzhled
- dark mode jako primární varianta, light mode jako sekundární
- vysoký kontrast pro trading data
- lehce futuristický, ale stále seriózní styl
- kompaktní, hustý layout bez chaosu
- důraz na rychlou orientaci očima
- čísla a stavy musí být čitelnější než dekorace
- design musí působit jako nástroj pro reálné používání, ne jako template

## Design language
Použij:
- Jetpack Compose + Material 3
- vlastní trading dashboard vizuální vrstvu nad Material 3
- zaoblené karty
- jemné stíny nebo tonal surfaces
- jemné zvýraznění aktivních bloků
- status badgy
- chips
- mini trend indikátory
- progress prvky
- ikonografii pro risk, trend, obchod, pozici, warning, learning, výkon

## Typografie
- silná hierarchie textu
- velká KPI čísla
- kompaktní sekundární metadata
- timestampy menší, ale velmi čitelné
- názvy sekcí jasné a konzistentní
- tabulková/monospace čísla tam, kde to pomůže čitelnosti cen, pnl a procent

## Karty
Každá hlavní karta musí mít:
- jasný titul
- hlavní hodnotu
- sekundární kontext
- timestamp
- stavový badge
- možnost otevřít detail
- info ikonku pro vysvětlení
- volitelně mini trend nebo sparkline, pokud to dává smysl

## Dashboard styl
Dashboard musí působit jako kombinace:
- trading terminálu
- executive KPI přehledu
- live operations monitoru

To znamená:
- horní část = nejdůležitější KPI
- střed = signály, otevřené pozice, warnings
- spodní část = trendy, výkon, learning a health souhrny
- nejdůležitější bloky musí být viditelné bez dlouhého scrollu

## Signálové karty — moderní vzhled
Každá signálová karta pro měnu musí vizuálně ukázat:
- směr doporučení
- sílu signálu
- confidence
- režim
- čerstvost dat
- důvod rozhodnutí

Použij například:
- barevný levý akcent
- badge „KOUPIT / PRODAT / VYČKAT / BLOKOVÁNO“
- vizuální prvek síly signálu
- mini rozpad metrik pod hlavní akcí
- timestamp ve spodní části karty

## Grafy — moderní styl
Grafy musí být:
- čisté
- čitelné i na mobilu
- bez zbytečné vizuální hlučnosti
- s jasně čitelnými osami/legendou pouze tam, kde jsou nutné
- s možností přepínání období
- s viditelným timestampem datového rozsahu
- s kontextovou legendou nebo info menu

## Animace
Použij jemné animace:
- přechody mezi stavy
- jemný update hodnot
- expand/collapse detailů
- shimmer loading
- žádné agresivní nebo pomalé animace

## Stavové komponenty
Navrhni konzistentní komponenty pro:
- OK
- INFO
- VAROVÁNÍ
- KRITICKÉ
- OFFLINE
- STALE DATA
- LIVE
- LEARNING ACTIVE
- RISK HIGH

## Responzivita a hustota informací
Optimalizuj pro:
- běžné Android telefony
- vysokou informační hustotu bez nepřehlednosti
- portrait primárně
- tablet layout jako bonus, pokud to stihneš

## Co chci konkrétně od návrhu designu
Dodej:
1. design principles
2. color/token systém
3. typography systém
4. spacing systém
5. card system
6. badge/status system
7. chart styling rules
8. ikony a vizuální jazyk
9. návrh dashboard composition
10. návrh vzhledu jednotlivých sekcí
11. návrh prázdných/loading/error stavů
12. doporučení pro dark/light theme
13. návrh reusable design komponent

Povinné:
Nechci jen technickou appku.
Chci i **promyšlený moderní design návrh**, který bude působit profesionálně a aktuálně v roce 2026.

---

# TECHNICKÁ ARCHITEKTURA

## Doporučené moduly
Navrhni modulárně:
- `app`
- `core-ui`
- `core-domain`
- `core-data`
- `feature-dashboard`
- `feature-trades`
- `feature-positions`
- `feature-performance`
- `feature-learning`
- `feature-health`
- `feature-settings`

Pokud je to moc těžké, udělej jednodušší multi-package verzi, ale čistě.

## Data vrstva
Navrhni:
- repository interfaces
- DTO → domain mappers
- Firestore listeners jen tam, kde dávají smysl
- kombinaci live stream + cache + throttling
- minimální počet čtení
- offline fallback pro poslední známý snapshot

## Výkon a cena
Protože bot může používat Firebase:
- minimalizuj reads
- nepřipojuj listener na všechno
- používej agregované snapshoty tam, kde to jde
- počítej složitější grafy z cached/aggregated dat
- odděl rychle se měnící data od historických
- u velkých kolekcí používej paging
- nečti celé trade history při startu

## Doporučený backend-friendly přístup
Pokud analýza ukáže, že přímé čtení z mnoha kolekcí je drahé, navrhni lehkou vrstvu snapshot dokumentů, např.:
- `dashboard_snapshot`
- `health_snapshot`
- `positions_snapshot`
- `learning_snapshot`
- `signals_snapshot`

Ale jen pokud to skutečně dává smysl.
Preferuj minimální zásah do backendu.

---

# POVINNÉ VÝSTUPY OD CLAUDE CODE

## 1. Nejdřív analyzuj projekt
Vypiš:
- nalezené zdroje dat
- klíčové kolekce a schémata
- co už existuje
- co chybí
- jaká data se hodí pro appku
- kde hrozí vysoké Firestore reads

## 2. Potom navrhni finální architekturu appky
Včetně:
- package/modul struktury
- datových modelů
- repository rozhraní
- screen modelů
- navigace
- refresh strategie
- cache strategie
- work manager / sync přístup, pokud je potřeba

## 2b. Současně dodej integrovaný design návrh
Ne jako samostatnou odbočku, ale jako součást implementace.

Dodej:
- design principles
- barevný/token systém
- typografický systém
- spacing systém
- card systém
- status/badge systém
- chart styling rules
- dashboard composition pravidla
- pravidla pro timestamp komponenty
- návrh reusable UI komponent
- pravidla pro loading/empty/error stavy
- dark/light theme pravidla

Každý z těchto bodů musí být následně vidět i v konkrétním kódu a screen návrhu.

## 3. Potom implementuj
Chci plnohodnotný základ aplikace, ne jen slovní návrh.

Implementuj minimálně:
- projekt structure
- navigation
- theme
- základní design system
- fake + real data integration strategy
- dashboard screen
- trades screen
- positions screen
- performance screen
- learning screen
- health screen
- settings screen
- reusable info dialog / context menu komponentu
- timestamp komponentu
- chart komponenty
- loading/empty/error states

## 4. Pokud data v backendu nestačí
Navrhni minimální změny v Python botu.
Dodej i konkrétní návrhy, kde přesně doplnit:
- snapshot docs
- timestamps
- agregace
- signal summary dokument
- health summary dokument
- lightweight mobile-friendly payload

---

# GRAFY — CO MÁ SMYSL
Použij grafy jen tam, kde pomáhají rozhodování.

## Preferované grafy
- equity curve
- cumulative pnl
- rolling win rate
- rolling EV
- learning health trend
- feature weight trend
- bandit/convergence trend
- trade frequency trend
- signal frequency trend
- timeout share trend
- exposure split
- performance by symbol/regime
- pnl distribution

## Nepoužívej
- dekorativní grafy bez rozhodovací hodnoty
- příliš mnoho tiny charts bez čitelnosti
- grafy bez timestamp a bez popisu

---

# DŮRAZ NA REÁLNÉ TRADING USE-CASE
Aplikace nesmí být jen hezká.
Musí pomoci odpovědět na otázky jako:
- běží bot?
- má čerstvá data?
- obchoduje?
- má otevřené pozice?
- zhoršuje se výkon?
- roste drawdown?
- funguje learning?
- které symboly selhávají?
- které režimy fungují?
- proč byl signál blokovaný?
- je problém ve filtrech?
- je problém v databázi?
- jsou data stale?
- má bot doporučení koupit/prodat/vyčkat pro konkrétní měnu?
- kdy byla každá informace naposledy aktualizována?

---

# DOPORUČENÁ ROZŠÍŘENÍ A VYLEPŠENÍ
Tato část rozšiřuje původní zadání. Nevyhazuj ji; použij ji jako doporučený plus scope tam, kde dává smysl.

## Vysoce přínosná rozšíření
- detail symbolu jako samostatný screen: live signal + výkon + trade history + regime summary
- watchlist oblíbených měn
- připnuté KPI na dashboard
- rychlý přepínač období 24h / 7d / 30d
- explainability panel pro poslední rozhodnutí bota
- heatmap výkonu symbol × režim
- timeline warningů a chyb
- lokální notifikace pro kritické stavy a silné signály
- read-only production monitoring režim
- drill-down z dashboard karet do detailu
- dashboard personalizace pořadí bloků
- kompaktní / rozšířený režim zobrazení
- export screenshot-friendly report view
- detail varování s historií a doporučenou akcí

## Rozšíření pro signály
- seznam posledních signálů mimo dashboard
- filtr signálů dle symbolu, stavu a síly
- porovnání „signal issued“ vs „trade executed“
- zobrazení důvodu, proč signál nevedl k obchodu
- stale signal indikace
- zobrazení confidence trendu pro symbol

## Rozšíření pro learning a explainability
- explainability panel pro EV / WS / confidence / regime / feature flags
- srovnání posledních N rozhodnutí
- feature contribution summary, pokud to backend dovolí
- mini timeline změn vah / health / convergence
- zobrazení policy/risk zásahu do finálního rozhodnutí
- rozpad „proč bot vzal / nevzal obchod“

## Rozšíření pro health a ops
- timeline reconnect událostí
- trend „no-signal“ období
- trend stale dat
- přehled backend chyb seskupených dle typu
- monitoring snapshot freshness
- odlišení problému dat, rozhodování, exekuce a DB vrstvy

## Rozšíření pro UX
- připnutí oblíbených symbolů nahoru
- sticky filter bar
- rychlé segmentované přepínače
- shimmer skeletons místo skákání layoutu
- offline banner
- jasný refresh stav
- rychlé kontextové akce z karet

---

# IMPLEMENTAČNÍ PRAVIDLA
- vše česky
- žádné placeholder bláboly
- maximálně využij reálná data z existujícího projektu
- timestamp u všech důležitých dat
- info menu u všech důležitých metrik
- moderní Compose UI
- profesionální architektura
- čistý kód
- rozšiřitelnost
- dobré loading/error states
- připravenost na produkční provoz

---

# OPTIMALIZACE ZADÁNÍ — KRITICKÉ DOPLNĚNÍ
Po prvním návrhu vše ještě jednou kriticky projdi a optimalizuj.

## Zkontroluj:
- co je zbytečné
- co je duplicitní
- co je příliš drahé na čtení
- co by mělo být agregované
- co chybí pro skutečný provoz
- co chybí z UX pohledu
- co chybí z debug/ops pohledu
- co chybí z pohledu timestampů a data freshness
- co chybí v signal cards
- co chybí v learning diagnostics
- co chybí v explainability vrstvě
- zkontroluj, zda design není jen popsaný, ale skutečně zakomponovaný do všech hlavních sekcí
- zkontroluj, zda dashboard působí moderně i při vysoké hustotě dat

## Poté:
- přidej vylepšení
- zjednoduš zbytečnosti
- zachovej maximum užitečné informační hodnoty
- napiš, proč je finální struktura lepší než původní zadání

---

# FORMÁT ODPOVĚDI
Postupuj v tomto pořadí:

1. analýza existujícího Python projektu a datových zdrojů
2. návrh finální architektury appky
3. návrh UI/UX struktury všech sekcí
4. návrh datových modelů a repository vrstvy
5. návrh minimalizace Firestore reads
6. návrh případných minimálních backend změn
7. integrovaný design systém a reusable komponenty
8. implementace kódu
9. závěrečná optimalizace a vylepšení zadání
10. krátké shrnutí, co je hotové a co je připravené pro další rozšíření

---

# DŮLEŽITÉ
Chci **reálný implementační výstup**, ne jen brainstorming.
Když něco v backendu chybí, navrhni to konkrétně.
Když něco nejde ověřit, označ to transparentně.
Vždy preferuj řešení použitelné v produkci.

Začni analýzou projektu `C:\Projects\CryptoMaster_srv`.
