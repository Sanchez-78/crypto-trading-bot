# Codex zadání: obnova dokončených svíček nezávislá na fázi plánovače (2026-11-09)

**Pro:** Codex (analýza + implementace v pracovním stromu). **Review:** Claude (reviewer-agent) / operátor.
**Repozitář:** `C:\Projects\CryptoMaster_srv`, větev `main`, pracovní strom je záměrně dirty.
**Režim:** pouze PAPER. Žádný deploy, commit, push ani přístup na server (`AGENTS.md`).
**Nasazení:** až po zmrazeném výsledku C1 (~2026-11-16) a po nezávislém review. Do té doby
se bot nesmí restartovat (`docs/OPERATING_STATE.md`), takže tvůj diff zůstává jen lokálně.

Postup: **Fáze A** (ověř nález, nic neměň) → **Fáze B** (oprava + testy) → **Fáze C** (report).

---

## 1. Problém (ověřeno na serveru, detail `_workspace/62_stale_market_data_rejections_since_restart.md`)

Po restartu bota 2026-11-09 07:30:41 UTC začal router zamítat kandidáty P0.8+ kódem
`REJECT_STALE_MARKET_DATA` (118× za ~3 h, 87 vstupů; předchozí 2 dny 0×).

Mechanismus:
1. `src/services/p0_8_plus_live_pipeline.py:383-420` (`_run_neural_scheduler`): pevné
   deadliny po 60 s, fáze v minutě = okamžik startu procesu. Mezi deadliny mohou
   přijít „neuronová“ probuzení jen pro BTCUSDT (`run_tick(symbols=("BTCUSDT",))`).
2. `src/services/p0_8_plus_live_pipeline.py:293-295` → `p0_8_plus_shadow_evaluator.evaluate_symbol`
   pro 7 symbolů postupně → `candle_cache_v1.CandleCache.get_candles(symbol, completed_only=True)`.
3. `src/services/candle_cache_v1.py:94-98`: refresh jen když `now − last_attempt >= refresh_seconds`
   (60 s). Čas fetch daného symbolu v ticku kolísá (předchozí symboly trvají různě dlouho);
   je-li rozdíl o kousek pod 60 s, refresh se přeskočí a vrátí se snapshot z minulého ticku.
4. `p0_8_plus_shadow_evaluator.py:384-394`: `market_data_event_time_ms = open_time poslední
   dokončené svíčky + 60 000`; `signal_router.py:235-239` zamítne při stáří > 90 000 ms
   (`SHADOW_MAX_DATA_AGE_MS`). Při přeskočeném refreshi je stáří ≈ (sekunda fáze) + 60 s.

Důkaz (sekunda v minutě řádků `[P0_8_PLUS_LIVE] tick complete` v syslogu):
- předchozí proces :15–:19 → stáří při přeskoku ≈ 75–79 s → 0 stale;
- od 07:31 :44–:50 → ≈ 104–110 s → 118 stale, všechny na :44–:48.

Vedlejší důsledek i při „dobré“ fázi: přeskočený refresh znovu vyhodnotí předchozí
svíčku (stejné `signal_id`) a nová svíčka toho symbolu se v dané minutě nevyhodnotí vůbec.

## 2. Fáze A — ověř (nic neměň)

- Přečti uvedené řádky a potvrď nebo vyvrať mechanismus. Pokud najdeš jiný důvod, zastav
  se a popiš ho v reportu (Fáze B pak jen tehdy, je-li oprava jasná).
- Odhadni z kódu (ne ze serveru), jak často k přeskoku dochází a zda ho způsobují i BTC
  neuronová probuzení.

## 3. Fáze B — oprava

Cíl: dokončená svíčka, která se uzavřela před vyhodnocením, se má dostat do vyhodnocení
bez ohledu na fázi plánovače a bez ohledu na jitter mezi symboly.

Možnosti (vyber jednu a zdůvodni; jiná je v pořádku, pokud je menší a bezpečnější):
- **A — cache:** v režimu `completed_only` obnovit, když se od posledního *pokusu* uzavřela
  nová minuta (`floor(now/60) > floor(last_attempt/60)`), s ochranou proti bušení při chybě.
  Pozor: mění význam `refresh_seconds` v tomto režimu; dnešní testy
  `tests/test_completed_candle_cache.py` (refresh 600 s, posun hodin o 61–150 s, očekávají
  jediný fetch) by se změnily — u každého změněného testu napiš, proč původní záruka
  (nepovýšit částečnou svíčku, nebušit po chybě, oddělené cutoffy symbolů) dál platí.
- **B — plánovač:** zarovnat deadliny na začátek minuty + malý offset (např. 2–5 s) a
  zajistit refresh v každém ticku (např. tolerance v podmínce refreshe nebo `force_refresh`
  z pipeline jen pro pravidelný tick, ne pro BTC probuzení).

Tvrdé podmínky:
- Nejvýš ~1 REST fetch za minutu na symbol v ustáleném stavu (dnes stejně), žádné
  bušení po chybě (`test_unsuccessful_refresh_never_advances_completed_cutoff_or_hammers_fetch`).
- Částečná svíčka se nikdy nesmí stát dokončenou jen plynutím času.
- Limit 90 s neměnit — je to záměrná ochrana proti zamrzlé cache.
- Neměnit generátory, router, prahy, TP/SL, náklady, limity průzkumu, CONTROL podíl.
- Diagnostika (doporučeno, bez změny rozhodnutí): u `REJECT_STALE_MARKET_DATA` dostat
  `data_age_ms` do logového řádku `[P0_8_PLUS_LIVE]`, ať je příště vidět ze syslogu.
- Testy: nový test, který bez opravy selže (ověř mutací — vrať opravu a ukaž selhání),
  s injektovanými hodinami simulující fázi :47 a jitter mezi symboly. Žádný test nesmí sahat
  na runtime soubory (`AGENTS.md`, porovnej SHA-256 před a po).
- Spouštěj jen cílené soubory: `tests/test_completed_candle_cache.py`,
  `tests/test_candle_cache_v1.py` a testy pipeline/evaluátoru, které tvou změnu pokrývají.

## 4. Fáze C — report

`_workspace/63_codex_candle_refresh_fix.md` česky:
- výsledek Fáze A (potvrzeno / vyvráceno, s `soubor:řádek`);
- zvolená varianta a proč, přesný seznam změněných souborů;
- výsledky testů (počty, příkazy), důkaz mutace, SHA-256 runtime souborů před/po;
- dopad na REST frekvenci a na populaci kandidátů (kvalitativně — žádná tvrzení o ziskovosti);
- co je `NOT_VERIFIED` (zejména chování na serveru).
