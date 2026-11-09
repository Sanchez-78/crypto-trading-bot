# `REJECT_STALE_MARKET_DATA` od restartu 2026-11-09 07:30 UTC

Autorita: `docs/OPERATING_STATE.md`. Nález z monitoringu (SSH read-only), žádný zásah.
Oprava je odložena až po zmrazeném výsledku C1 (viz níže proč).

## KOŘENOVÁ PŘÍČINA (ověřeno 2026-11-09 ~10:45 UTC) — fáze plánovače po restartu

Hypotézy 1–3 níže jsou překonané. Mechanismus:

1. `p0_8_plus_live_pipeline._run_neural_scheduler` (`:383-420`) tiká s pevnými deadliny
   po 60 s; fáze v minutě je dána okamžikem startu procesu.
2. `candle_cache_v1.get_candles` (`:94-98`) obnoví data jen při
   `now − last_attempt >= refresh_seconds` (60 s). Symboly se vyhodnocují postupně, takže
   čas fetch symbolu v ticku kolísá; když je rozdíl o kousek pod 60 s, obnova se přeskočí
   a použije se snapshot z předchozího ticku.
3. Poslední dokončená svíčka v tom snapshotu má stáří ≈ (sekunda fáze v minutě) + 60 s.
   Limit je 90 s (`SHADOW_MAX_DATA_AGE_MS`), takže přeskočená obnova vede ke stale
   zamítnutí právě tehdy, když fáze > ~30 s.

Důkaz (sekunda v minutě v razítkách syslogu):

| Období | Řádky `[P0_8_PLUS_LIVE] tick complete` | Stale |
|---|---|---|
| 11-07 – 11-09 00:00 (předchozí proces) | :15–:19 (stáří při přeskoku ≈ 75–79 s < 90) | 0 |
| 11-09 od 07:31 (restart 07:30:41) | :44–:50 (stáří ≈ 104–110 s > 90) | 118, vše na :44–:48 |

Kódová změna z 07:16/07:30 (`paper_learning_budget.py`, `paper_source_learning.py`,
diff proti `/opt/cryptomaster_deploy_backups/probe-volume-20261109T071608Z/`) jen čte
limity a CONTROL podíl z env; s časováním nesouvisí.

Důsledky:
- **Pro C1:** podíl ztracených kandidátů závisí na náhodné fázi restartu. Každý restart bota
  během C1 by náhodně změnil složení populace → **během C1 bota nerestartovat**.
- I při „dobré“ fázi (před restartem) přeskočený tick znovu vyhodnotí předchozí svíčku
  místo nové, takže nová svíčka toho symbolu se v tu minutu nevyhodnotí vůbec. Ztráta
  kandidátů tedy existovala i dřív, jen nebyla vidět jako stale kód.
- Oprava zadána Codexu: `docs/codex_prompts/CODEX_CANDLE_REFRESH_PHASE_FIX_2026-11-09.md`.
  Nasazení až po zmrazeném výsledku C1 a po nezávislém review diffu.

## Ověřeno (syslog, `[P0_8_PLUS_LIVE] … admitted=… code=…`)

| Kód | 2026-11-09 00:00–10:16 UTC | 2026-11-07 00:00 – 11-09 00:00 (`syslog.1.gz`) |
|---|---|---|
| P0_REJECT_PAPER_LEARNING | 706 | 1 506 |
| REJECT_NEGATIVE_NET_EDGE | 206 | 1 142 |
| **REJECT_STALE_MARKET_DATA** | **118** | **0** |
| P0_ADMIT_EVIDENCE_COLLECTION | 87 | 403 |
| REJECT_RISK_DENIED | 18 | 0 |
| REJECT_EDGE_BELOW_BUFFER | 1 | 3 |

- Stale zamítnutí po hodinách: 07 → 44 (jen 07:30–07:59), 08 → 27, 09 → 37, 10 → 10.
  Všech 7 symbolů (XRP 24, DOT 23, BNB 17, ETH 16, SOL 14, BTC 12, ADA 9), strategie
  `trend_cost_aware` a `sideways_mean_reversion`, všechny řádky `quote=live`.
- Bot restartován 07:30:41 UTC (`ActiveEnterTimestamp`). Cutoff C1 `prereg_after=1794209516`
  = 07:31:56 UTC → **zamítnutí existují od začátku populace C1**, jsou součástí jejích podmínek.
- Změněno na serveru těsně před restartem: drop-in `zzzzzzzzzz-probe-volume.conf` (07:16;
  480/den, 30/h, cooldown 300 s, min. net −25 bps, prázdný blacklist),
  `zzzzzzzzzzz-learning-collect.conf` (07:30; CONTROL 1,0), soubory
  `paper_source_learning.py` a `paper_learning_budget.py` (07:30). Kód evaluátoru,
  routeru, cache svíček a generátorů je beze změny od 2026-10-23.
- `PAPER_COMPLETED_CANDLE_LEARNING_ENABLED=true` platí od 2026-10-23 (není nové).

## Mechanismus (kód)

`p0_8_plus_shadow_evaluator.py:384-410`: v režimu dokončených svíček se
`market_data_event_time_ms = open_time poslední svíčky + 60 000` a router
(`signal_router.py:235-239`) zamítne, když `now − close_ms > SHADOW_MAX_DATA_AGE_MS`
(výchozí 90 000 ms, env na serveru nepřepsán). Zamítnutí tedy znamená, že poslední
dokončená svíčka v cache je > 90 s po svém uzavření, tj. cache svíček nebo plánovač
zaostává o víc než ~30 s za očekávaným obnovením.

## Hypotézy (NEOVĚŘENO)

1. Zpoždění smyčky/CPU po zvýšení objemu průzkumu (load average ~2,9; bot loguje
   ~13 000 řádků/min).
2. Změna v `paper_source_learning.py`/`paper_learning_budget.py` mění, kdy a pro které
   kandidáty evaluátor běží (např. neuronový/plánovaný wake mimo fázi svíčky).
3. Zpoždění REST pollingu `candle_cache_v1` (refresh 60 s) — proti tomu mluví, že předtím
   za 2 dny nebylo ani jedno zamítnutí.

Stáří v ms se neloguje (`_reject` detail jde jen do vyhodnocení, ne do řádku
`[P0_8_PLUS_LIVE]`), proto hypotézy nelze rozlišit z logu.

## Proč teď neopravovat

- Zmrazení sběru během C1 (`OPERATING_STATE.md`): oprava by změnila, kteří kandidáti
  vstupují, tj. cílovou populaci předregistrace uprostřed hodnocené množiny.
- Nasazení kódu bota = restart = ukončení otevřených pozic v populaci C1.
- Podmínka je stabilní od začátku C1, takže C1 měří konzistentní populaci.

## Po zmrazeném výsledku C1 (fronta)

1. Logovat `data_age_ms` u stale zamítnutí (diagnostika, bez změny rozhodnutí).
2. Podle naměřeného stáří rozlišit hypotézy 1–3; teprve pak oprava příčiny (ne zvýšení limitu
   naslepo — limit 90 s je záměrná ochrana proti zamrzlé cache, viz komentář v evaluátoru).
3. Současně posoudit `REJECT_RISK_DENIED` (18×, nové od restartu) vůči cíli „virtuální ztráta
   nevadí“ — rozhodnutí o risk guardu patří operátorovi.
4. Snížit objem logu bota (~13 000 řádků/min); kvůli němu journal drží jen ~15 min a syslog
   roste ~3,6 GiB/den (`_workspace/61`).
