# Codex: oprava fáze obnovování dokončených svíček

Datum: 2026-11-09. Zadání: `docs/codex_prompts/CODEX_CANDLE_REFRESH_PHASE_FIX_2026-11-09.md`.

**Výsledek: příčina potvrzena lokálně, oprava implementována a otestována.**
Finální cílená sada: **112 PASS, 0 FAIL, 0 ERROR**. Mutace prokázaly, že nové testy
zachytí původní chybu i odstranění ochrany proti opakovaným požadavkům po chybě.
Změny jsou pouze v pracovním stromu; nový příznak je výchozí vypnutý.
Nebyl proveden SSH, deploy, restart, commit, push ani změna konfigurace sběru C1.
Probíhající C1 nadále běží s původním chováním. Nasazení/zapnutí patří až za
zmrazený výsledek C1 a nezávislé review, nikoli automaticky k určitému datu.

## 1. Výchozí stav a rozsah

- Pracovní adresář: `C:\Projects\CryptoMaster_srv`.
- Větev před/po: `main`; HEAD před/po: `4fb917e87cea9a512c56a6ebced1e5d770f0d144`.
- Před úpravami 972 položek v `git status --short`. Existující změny byly zachovány.
- Výchozím bodem je aktuální pracovní strom, **nikoli obsah HEAD**. Přesný diff
  tohoto úkolu: `candle_refresh_20261109/task.diff` vedle tohoto reportu.
- Hash manifest zachycuje 520 souborů včetně zdrojů, testů a šesti chráněných
  runtime souborů. Změnilo se právě šest vyjmenovaných souborů; ostatních 514
  z tohoto manifestu zůstalo shodných. Nejde o hash všech souborů celého disku.
- Artefakty: `candle_refresh_20261109/before.json`, `after.json`, kopie původních
  šesti souborů, stavy gitu, diff, JUnit XML a mutační logy. Dřívější hotová
  zadání, strategie ani audit učení nebyly znovu zpracovávány.

## 2. Fáze A — ověření příčiny

Následující odkazy jsou na aktuální lokální soubory; číslování po opravě se u
cache a logování posunulo. Původní soubory jsou zachovány mezi artefakty.

| Krok | Ověřený kód | Důsledek |
|---|---|---|
| Živá dosažitelnost | `start.py:48`, `bot2/main.py:1718` | Hlavní proces spouští existující pipeline s intervalem 60 s. |
| Pravidelné deadliny | `src/services/p0_8_plus_live_pipeline.py:384`, `:391`, `:402` | První deadline je aktuální monotonic čas; další jsou jeho násobky 60 s. Nejde o zarovnání na UTC minutu. |
| BTC probuzení | stejný soubor, `_run_neural_scheduler` | Mezi deadliny běží další `run_tick(symbols=("BTCUSDT",))`; nepřepisuje pravidelné deadliny. |
| Sekvenční symboly | stejný soubor, `run_live_tick`, `:293` | Doba zpracování předchozích symbolů posouvá okamžik fetch konkrétního symbolu. |
| Completed pohled | `src/services/p0_8_plus_shadow_evaluator.py:330`, `:335` | Evaluátor používá sdílenou cache s `completed_only=True`. |
| Původní TTL | `src/services/candle_cache_v1.py:106` (původně `:96`) | Obnova jen při `now - last_attempt >= refresh_seconds`, obvykle 60 s. Přeskok nepřepisuje `last_attempt`. |
| Čas market inputu | `src/services/p0_8_plus_shadow_evaluator.py:384`, `:394` | Timestamp je open time poslední dokončené svíčky + 60 000 ms. Stejná svíčka dává stejné signal ID. |
| Freshness veto | `src/services/signal_router.py:235`, `:238`; evaluátor `:166`, `:410` | Router zamítá stáří větší než 90 000 ms. Tento limit zůstal beze změny. |

Příklad z reprodukčního testu: úspěšný fetch v `T + 47,4 s`, následující
vyhodnocení v `T + 107,1 s`. Rozdíl je 59,7 s, takže původní cache neobnoví
svíčky. Poslední známá dokončená svíčka má close time `T`; její stáří je
107 100 ms. Nová dokončená svíčka s close time `T + 60 s` se nevyhodnotí.
Při fázi :15 by obdobný přeskok dal stáří přibližně 75 s, prošel by freshness
veto, ale pořád by opakoval starou svíčku a signal ID.

Tím je mechanismus popsaný v zadání potvrzen nezávisle čtením kódu i testem.
Počty 118 stale / 87 vstupů, sekundy serverových logů a porovnání ranního
serverového deploye se zálohou jsou **převzatá pozorování** z `_workspace/62…`;
v tomto úkolu nebyly znovu ověřovány na serveru.

### Odhad četnosti z kódu

Po úspěšném pravidelném fetch je rozdíl do následujícího ticku přibližně
`60 + jitter_n - jitter_(n-1)`. Pokud je nový jitter menší, obnova se přeskočí.
Při konstantním jitteru není přeskok žádný. Při střídání pomalejšího a rychlejšího
ticku může odpadnout každý druhý pravidelný refresh. Za předpokladu úspěšných
požadavků, žádných dalších čtenářů a rozsahu jitteru menšího než minuta tedy
jde přibližně o **0 až 50 % pravidelných obnov**; přesnou četnost z kódu nelze
určit bez distribuce skutečných časů. Po přeskoku se čas posledního pokusu
neposune, takže následující pravidelný tick má obvykle již téměř 120 s odstup.
Jde o fetch sloty, nikoli přímo procento kandidátů nebo obchodů.

BTC neuronová probuzení používají stejný `last_attempt`. Mohou tedy přesunout
poslední fetch mimo pravidelný tick a způsobit jeho další přeskočení. Pokud
již stáhla data v aktuální minutě, opětovné použití této cache je správné;
problém je překročení hranice minuty při ještě nevypršených 60 s. Stejnou
cache umí číst i existující legacy cesta dynamického exitu
(`paper_trade_executor.py:2762`); ta ani její pravidla nebyly měněny. Z počtu
samotných probuzení proto nelze odvodit počet ztracených kandidátů.

## 3. Fáze B — zvolená oprava

**Varianta A: obnova completed cache podle UTC minutového bucketu.** Je lokální
vlastností zdroje dat a funguje pro pravidelný tick i BTC probuzení. Nevyžaduje
posouvání plánovače, toleranční konstanty ani nucené fetch z pipeline.

Příznak `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED` se čte při vytvoření
`CandleCache`; výchozí stav je `false`, neplatné hodnoty jej nezapnou. Tím je
splněno pravidlo AGENTS.md „nové chování za env příznakem s výchozím vypnuto“.
V tomto úkolu nebyl nastaven v žádném runtime env, .env ani service drop-in.

Při zapnutém příznaku a `completed_only=True`:

1. První pokus naplní dosud chybějící cache jako dosud.
2. Další běžný pokus vyžaduje `floor(now / 60) > floor(last_attempt / 60)`.
3. Pokud poslední pokus selhal, navíc musí uplynout
   `max(60, refresh_seconds)` sekund. Výjimka, prázdná odpověď i `None` se
   počítají jako neúspěch, včetně úplně prvního pokusu.
4. Snapshot a cutoff se mění jen po úspěšné odpovědi pod stávajícím zámkem.
5. Filtrace stále používá `min(now, last_success_fetch_start)`. Pouhé stárnutí
   cached partial svíčky, výpadek ani pomalá odpověď přes hranici minuty ji
   nepovýší na dokončenou. Cutoffy zůstávají oddělené po symbolech.

V tomto zapnutém režimu `refresh_seconds=600` již neznamená desetiminutový TTL
úspěšné completed cache; stále znamená nejméně 600 s prodlevu po chybě.
Legacy pohled a vypnutý příznak zachovávají původní TTL. Stávající explicitní
`force_refresh=True` zůstává výjimkou; živý evaluátor jej nepoužívá.

Původní testy s TTL 600 s nebyly oslabeny ani přepsány: běží na výchozím
vypnutém režimu se stejnými očekáváními jako dříve. Nové testy zapnutého režimu
samostatně dokazují nepovýšení partial baru po neúspěchu, prodlevu 60/600 s,
oddělené symbolové cutoffy, legacy-first snapshot, rollback hodin a fetch
přes hranici minuty. Kontrolují i výjimku, prázdnou odpověď a `None`.

### Přesný seznam změněných souborů

| Soubor | Změna a důvod |
|---|---|
| `src/services/candle_cache_v1.py` | Opt-in minutová obnova a prodleva po chybě; odstranění závislosti obnovy na jitteru vůči 60s TTL. |
| `src/services/p0_8_plus_live_pipeline.py` | Do existujícího řádku kandidáta přidáno `data_age_ms`; bez změny admission nebo dalšího logového řádku. |
| `tests/test_completed_candle_cache.py` | 23 nových parametrizovaných případů pro fáze, BTC wakes, limity požadavků, safe default a cutoffy. |
| `tests/test_completed_strategy_pipeline.py` | 2 případy přes skutečné generátory/evaluátor/router: příznak off/on, nové signal ID a freshness; následný výpadek zůstává zamítnutý. |
| `tests/test_p0_8_plus_live_pipeline.py` | 3 případy logování skutečného stáří při vyhodnocení; stale odmítnutí nikdy nevolá executor. |
| `src/services/LOGIC.md` | Popis příznaku, změny významu TTL, backoffu, diagnostiky a odloženého zapnutí po C1. |

Zbývající nové soubory jsou pouze tento report a důkazní artefakty v
`_workspace/candle_refresh_20261109/` (plus JUnit výstupy existujícího runneru).
Generátory, router, TP/SL, náklady, limity průzkumu, CONTROL, risk, executor,
plánovač a reálné objednávky nebyly upraveny.

Diagnostická hodnota je přesně
`evaluation.evaluated_at_ms - signal.market_data_event_time_ms`, tedy stejná
časová reference jako při routerově rozhodnutí. Nevychází z pozdějšího času
logování. Testované hodnoty jsou 107 250, 90 001 i −100 ms; záporná hodnota
zachovává informaci o timestampu z budoucnosti. Pole se loguje u všech
kandidátů včetně `REJECT_STALE_MARKET_DATA`.

## 4. Testy a mutace

Testy běžely přes existující `_workspace/code_audit_20260921_runner.py` v
dočasném snapshotu kódu bez skutečných runtime databází a credentials, s
blokovanou externí sítí. Tím ani import `local_persistent_cache` nemohl
inicializovat skutečnou databázi projektu. Testovací soubory mimo zadání
nebyly spouštěny. Nové testy používají injektované hodiny a REST fixtures.

Příkaz výchozího a finálního běhu:

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_completed_candle_cache.py tests/test_candle_cache_v1.py tests/test_completed_strategy_pipeline.py tests/test_p0_8_plus_live_pipeline.py tests/test_neural_scheduler.py -q --tb=short
```

| Sada | Finální výsledek |
|---|---:|
| `test_completed_candle_cache.py` | 59 PASS |
| `test_candle_cache_v1.py` | 16 PASS |
| `test_completed_strategy_pipeline.py` | 8 PASS |
| `test_p0_8_plus_live_pipeline.py` | 26 PASS |
| `test_neural_scheduler.py` | 3 PASS |
| **Celkem** | **112 PASS, 0 FAIL, 0 ERROR, 0 SKIP** |

Výchozí sada před přidáním testů: 84 PASS. Finální pytest běh trval přibližně
5,2 s, mimo vytvoření kopie; šest již přítomných upozornění `datetime.utcnow()`
ve Firebase/outbox kódu. JUnit: `candle_refresh_20261109/baseline.xml`,
`final.xml`; přehled: `test_results.json`. Meziběhy po postupném doplnění testů
měly 109 a 111 PASS.

**RED před opravou:** po přidání nových testů a před úpravou zdrojového kódu
spuštěno:

```text
rtk python _workspace/code_audit_20260921_runner.py tests/test_completed_candle_cache.py tests/test_p0_8_plus_live_pipeline.py -k "phase_refresh_handles_symbol_jitter or logs_stale_age" -q --tb=short
```

Výsledek 7 očekávaných FAIL: fáze :00, :15, **:47**, :59 vracely starý bar;
tři logovací případy neměly `data_age_ms`. Důkaz: `candle_refresh_20261109/red.xml`.

**Mutace po opravě:** skript `candle_refresh_20261109/mutations.py` přepsal
zdroje pouze v dočasném testovacím snapshotu jejich skutečnými uloženými
verzemi před opravou. Nikdy nevracel změny v pracovním stromu nebo pomocí gitu.

```text
rtk python -X utf8 _workspace/candle_refresh_20261109/mutations.py C:\Users\JA30B~1\AppData\Local\Temp\code_audit_20260921_xyrw8957
```

| Mutace | Výsledek cílených testů | Význam |
|---|---:|---|
| Vrácení celé opravy cache na preimage | 6 FAIL, 1 PASS, 0 ERROR | Chybu zachytí všechny čtyři fáze, BTC wake před pravidelným tickem i skutečný router při zapnutém příznaku; default-off kontrola projde. |
| Vrácení logovací změny | 3 FAIL, 0 ERROR | Bez doplněného pole testy selžou. |
| Odebrání prodlevy po chybě, ponechání bucketu | 12 FAIL, 0 ERROR | Pouhý minutový bucket nestačí proti rychlému retry přes hranici minuty. |
| Obnovení opraveného kódu | 22 PASS, 0 ERROR | Všechny dotčené mutační testy znovu projdou. |

Podrobnosti: `mutation_results.json`, `revert_cache.log/.xml`,
`revert_diagnostic.log/.xml`, `remove_failure_backoff.log/.xml`, `restored.log/.xml`.
První přístup mutačního skriptu do dočasného adresáře zablokoval sandbox ještě
před změnou souborů; následný schválený běh uvedené ověření dokončil.

Další kontroly: AST všech pěti změněných Python souborů s gramatikou Pythonu
3.12 **PASS**; compile bez zápisu bytecode **PASS**; cílený `git diff --check`
**PASS**. Testovací interpret byl Python 3.14. Ruff **NOT_RUN**, není instalován.

## 5. SHA-256 runtime dat před/po

Všech šest souborů existovalo. V následující tabulce uvedený hash je **shodný
před prvním během i po všech testech a mutacích**. Úplné nezávislé před/po
hodnoty jsou v `before.json` a `after.json`.

| Soubor | SHA-256 před = SHA-256 po |
|---|---|
| `local_learning_storage/cache.sqlite` | `31767b56391e77b4143c1e1129b7fa2a4447f4c71f931469e512a4f01ed17646` |
| `data/paper_open_positions.json` | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| `server_local_backups/paper_adaptive_learning_state.json` | `9263583f87369276b82646e80d85e92433e6602858b0551204983d064a27c93c` |
| `server_local_backups/learning_state_phase1.json` | `fbf592e2fb30a6d0a1da4d2050c1136dc9718665653a28b498fa2163eaabf5e6` |
| `runtime/v5_quota_usage.sqlite` | `0a3bf519ac254cb670486ff3c9539ccf55385c9f1a17fe8b516f34cf79161b03` |
| `src/runtime/v5_quota_usage.sqlite` | `8b65fbaaccdc984882e1dacc112cbbd16c544fc3c36d58630684205e213f81e1` |

## 6. Dopad a hranice ověření

Při pozdějším zapnutí, úspěšném REST a dokončeném baru dostupném před zahájením
požadavku se nová minuta dostane k vyhodnocení i tehdy, když od posledního
fetch uběhlo např. jen 59,7 s. Nová svíčka má nové signal ID. Opakované
vyhodnocení stejné svíčky uvnitř minuty zachovává stejné ID.

Pro běžné completed čtení jde nejvýše o jeden pokus za UTC minutu a symbol.
Fázový test počítá **42 fetch pro 7 symbolů za 6 minut**, včetně mnoha BTC
probuzení; žádný pár symbol/minuta se neopakuje. Fetch na konci jedné a na
začátku další minuty mohou být blízko sebe: nejde o striktní klouzavý interval
60 s mezi každými dvěma úspěšnými požadavky. To je záměr varianty A. Po chybě
striktní prodleva zůstává. Výslovný `force_refresh` je nadále mimo tento limit.

Skutečný počet požadavků může proti chybovému přeskakování vzrůst zpět
k zamýšlenému rozpočtu přibližně 1/min/symbol; horní rozpočet se nezvyšuje.
U experimentálního completed nastavení TTL 600 s je změna úspěšné frekvence
výslovná, viz výše. Při defaultním 60s TTL také existující legacy čtenář sdílí
stejný čas pokusu a zámek; nevzniká druhá cache ani nový polling loop.

Populace kandidátů se po zapnutí změní: mohou přibýt kandidáti ze svíček,
které původně vypadly, a ubýt opakovaná vyhodnocení starého inputu. Negarantuje
to více otevřených pozic: ostatní generátory a centrální gates zůstávají
autoritativní. Změna nedokazuje ziskovost ani zlepšení učení a nesmí být
nasazena uprostřed zmrazené populace C1.

**NOT_VERIFIED / NOT_RUN:**

- Chování opravy na Hetzneru, serverová frekvence REST, latence a logy po
  restartu: žádný přístup na server ani nasazení nebyly součástí úkolu.
- Skutečný běh pod serverovým Pythonem 3.12: ověřena kompatibilní syntaxe,
  nikoli spuštění na tomto interpretu.
- Dostupnost final svíčky na straně Binance přesně na hranici minuty. Pokud
  se minuta uzavře až během HTTP požadavku, zůstává záměrně konzervativní
  cutoff z jeho začátku; oprava nepovoluje starou partial svíčku. Pomalý REST,
  výpadek nebo zamrzlá upstream data může nadále způsobit legitimní stale veto.
- Přesná produkční četnost přeskoků a kauzální podíl BTC wakes: z lokálního
  kódu lze určit mechanismus a podmíněné meze, nikoli skutečnou distribuci.
- Celá historická testovací sada, výkonnost serveru, edge, P/L a nezávislé
  review: mimo rozsah tohoto zadání.

Stav k předání: lokální diff připraven k review, bezpečný default vypnutý,
runtime evidence zachována, žádný zásah do běžícího C1.
