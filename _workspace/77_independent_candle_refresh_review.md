# Nezávislé review opravy obnovování dokončených svíček (2026-11-11)

Zadání: `docs/codex_prompts/INDEPENDENT_REVIEW_CANDLE_REFRESH_PHASE_FIX_2026-11-11.md`.
**Reviewer: Claude**, opravu nenapsal (autor Codex, `_workspace/63_codex_candle_refresh_fix.md`).
Rozšíření `deploy_bot_files.sh` napsal Claude a prověřil ho Codex odděleně (`_workspace/77_codex_deploy_allowlist_review.md`).
Při review jsem nesahal na bota, konfiguraci, C1 ani outcomes po cutoffu. Na server jsem se
připojil jen ke čtení hashů a k dry runu sandboxu bez instalace (popsáno v
`candle_fix_deploy_20261111/README.md`).

**Verdikt ke kódu: APPROVE. Připravenost nasazení: BLOCKED** (C1 není zmrazené a opravený
deploy skript čeká na re-review, viz níže).

## Přesný rozsah (ověřeno)

- Šest souborů má stejné SHA-256 jako Codexův `after.json`
  (`candle_cache_v1.py` `f3f9370c…`, `p0_8_plus_live_pipeline.py` `f2e4d28d…`, `LOGIC.md`
  `b209372a…`, tři testy). Drift není.
- Preimage obou modulů v `_workspace/candle_refresh_20261109/` je **bajtově shodný se
  serverem** (`23a90681…`, `6d07ce3c…`). Nasazovaný diff je tedy přesně
  (`difflib`, `candle_refresh_review_20261111/`):
  - `candle_cache_v1.py`: příznak `PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED` čtený v
    `__init__` (`:81-83`) a nová větev obnovy pro `completed_only` (`:107-114`) + docstring a
    `import os`;
  - `p0_8_plus_live_pipeline.py:300-305`: do existující logové řádky přidáno
    `data_age_ms = evaluation.evaluated_at_ms - signal.market_data_event_time_ms`.
  Jiná změna proti serveru není. Generátory, router, P0/risk/executor, TP/SL, náklady,
  limit 90 s, CONTROL ani cesta k REAL se nemění.

## Odpovědi na otázky zadání

1. **Příčina potvrzena** čtením kódu a vlastní simulací (níže). Bez příznaku se obnova
   řídí `now - last_attempt >= 60` (`:106`). Jitter symbolů a BTC probuzení posouvají
   `last_attempt`, takže se refresh těsně pod 60 s přeskočí a vyhodnotí se stará svíčka.
   Stáří ≈ fáze + 60 s, při fázi :47 tedy přes 90 s (veto `signal_router.py:235-239`).
   Serverová čísla (118 stale, fáze :44–:50) jsou **převzatá** z reportu 62, sám jsem je
   neměřil.
2. **Obnova v zapnutém režimu:** `new_minute and (last_attempt_succeeded or retry_ready)`
   (`:111-114`). Obnova proběhne v nové UTC minutě i po 59,x s a při BTC probuzení, nejvýš
   jednou za minutu a symbol. Po chybě (výjimka, prázdná odpověď nebo `None` se nezapíší do
   `_last_success`) navíc platí `max(60, refresh_seconds)`. Při posunu hodin zpět
   `new_minute` = false, data stárnou a router vetuje (fail-closed). `force_refresh` zůstává
   výjimkou.
3. **Nedokončená svíčka se nepovýší:** cutoff `min(now, fetched_at)` (`:139`) a kontrola
   `stamp + 60_000 <= cutoff` (`:147`) se nemění. V simulaci 0 povýšení ve všech scénářích.
   Cutoffy jsou per symbol (`_last_success[symbol]`). Legacy čtenáři sdílejí
   `_last_attempt`/`_last_success`; jejich úspěšný fetch v dané minutě je pro completed
   pohled platný snapshot, jejich chyba spouští stejný backoff.
4. **Bezpečný default:** výchozí `false`, čte se při konstrukci instance (singleton
   `get_default_cache()` vzniká až po startu procesu s prostředím). Cache bere i
   `1/yes/on`, deploy skript ale nově vyžaduje přesně `true`/`false`, takže přísnější je
   deploy. `data_age_ms` je přesně rozdíl, který počítá router se stejným `now_ms`
   (`signal_router.py:235`), a výsledky existují jen po úspěšném vyhodnocení routerem
   (`p0_8_plus_shadow_evaluator.py:399-424`), takže výpočet nemůže vyhodit výjimku a
   nemění admission.
5. **Nasaditelnost:** původní allowlist nestačil. Rozšíření v `9104b9b` dostalo od Codexu
   CHANGES_REQUIRED (P1 pořadí prostředí, P2 import ve stagingu, P3 připnuté hashe),
   opraveno v `e39a1b7` (`candle_fix_deploy_20261111/README.md`). **Opravený skript ještě
   neprošel re-review**, proto BLOCKED. Na serveru je stále stará verze `52d50fe7`.
6. **Populace:** zapnutí změní množinu kandidátů (víc čerstvých svíček, nová `signal_id`,
   méně opakovaných vyhodnocení staré svíčky). Musí jít o novou kohortu s vlastním markerem
   (`stage.log` `APPLIED OK` + čas), verzí kódu a nákladovým modelem, oddělenou od C1. Víc
   obchodů ani změna P/L nejsou účinek učení.

## Vlastní reprodukce (nezávislá na Codexových testech)

`candle_refresh_review_20261111/simulate.py`: skutečný `CandleCache` s injektovanými
hodinami, 6 h, 7 symbolů, pravidelné ticky v pevné fázi, jitter 0–0,8 s na symbol, 0–3 BTC
probuzení za minutu a fetch vracející i rozpracovanou svíčku jako Binance
(`simulation.json`):

| Scénář | Stale (> 90 s) | Nevyhodnocené uzávěry / symbol (z 358) | Fetche | Max fetch / symbol / min | Retry < 60 s po chybě | Povýšená partial |
|---|---:|---:|---:|---:|---:|---:|
| :47, vypnuto | 29,9 % | 108 | 1 752 | 1 | 0 | 0 |
| :47, zapnuto | **0 %** | **0** | 2 520 | 1 | 0 | 0 |
| :15, vypnuto | 0 % | **110** | 1 741 | 1 | 0 | 0 |
| :15, zapnuto | 0 % | **0** | 2 520 | 1 | 0 | 0 |
| :47, 5 % chyb, vypnuto | 33,3 % | 120 | 1 752 | 1 | 0 | 0 |
| :47, 5 % chyb, zapnuto | 6,3 % | 22 | 2 468 | 1 | 0 | 0 |

Ztráta svíček existuje i při „dobré“ fázi :15 (30 %), jen není vidět jako stale veto.
Oprava ji odstraní. REST vzroste asi o 44 % na zamýšlený rozpočet 1 požadavek za minutu na
symbol (7/min). Stale po chybě fetch je legitimní veto (backoff), ne vada.

## Testy a mutace

- Cílená sada (izolovaný runner): **112 PASS** (`tests.txt`), SHA šesti runtime souborů před
  a po shodné.
- Nezávislé mutace v izolované kopii (`mutations.json`): s opravou 93 PASS ve třech
  dotčených souborech. **Cache vrácená na serverovou verzi: 17 FAIL. Pipeline vrácená na
  serverovou verzi: 3 FAIL. Bez backoffu po chybě: 13 FAIL.** Po obnovení 93 PASS. Žádná
  chyba importu.

## Drobné poznámky (neblokují)

- **P3:** BTC probuzení těsně po hranici minuty (:00,x) stáhne svíčku M-1 jako dokončenou
  podle času zahájení requestu. Pokud by Binance agregovala poslední obchody s
  milisekundovým zpožděním, mohla by být minimálně neúplná. Totéž platí pro jakýkoli dřívější
  fetch u hranice, nejde tedy o novou vadu, jen o častější výskyt. Neověřeno proti Binance.
- **Informační:** cache přijímá i `1/yes/on`; to je konzistentní s dosavadním stylem a
  deploy je přísnější.

## Podmínky nasazení

1. Ověřené zmrazení C1 a provenance podle `docs/remediation/C1_FREEZE_DAY_RUNBOOK_2026-11-11.md`.
2. Re-review opraveného deploy skriptu `e39a1b7` (Codex) s výsledkem APPROVE.
3. Nasazení novým skriptem s `EXPECTED_SHA256` = `f3f9370c996624acb…` (cache) a
   `f2e4d28d1a5dad68…` (pipeline; plné hashe v `after.json`), drop-in s příznakem `true`,
   záznam markeru nové kohorty a kontrola po restartu (`data_age_ms`, fetch / symbol / min,
   podíl stale se stejným jmenovatelem).
