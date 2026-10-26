# Autonomní PAPER smyčka učení — předem stanovená pravidla (2026-10-26)

Operátor 26. 10. povolil autonomní nasazování změn k cíli (WR > 50 % a kladné
P/L) bez své přítomnosti. Tento dokument určuje **jediné** změny, které smí
smyčka provést, a podmínky pro ně. Pravidla jsou zapsaná **před** vyhodnocením;
na datech se nesmí ladit ani doplňovat.

## Výchozí realita

- Epocha od 25. 9.: 269 obchodů, −10,1 bps/obchod, horní mez −7,7 bps (STOP_NO_EDGE).
- Dřívější výzkum (`RESEARCH_*.md`): 10 rodin strategií bez OOS edge při ~15–18 bps nákladů.
- Žádná konfigurační páka v této smyčce edge nevytvoří. Smyčka umí jen přestat
  platit za průzkum, který nepomáhá, a nakonec zastavit zdroje bez edge.
  Dosažení cíle vyžaduje novou strategii — to je mimo autonomní rozsah.

## Stupně (jen env příznaky přes systemd drop-in)

| Stupeň | Změna | Nástroj |
|---|---|---|
| S1 | současný stav: adaptivní výběr + průzkum se záporným edge | — |
| S2 | `PAPER_COST_EXPLORATION_ENABLED=false` (adaptivní výběr zůstává) | `apply_stage.sh S2` |
| S3 | průzkum, adaptivní výběr, completed-candle a Stonkfly kontext vypnuty; `PAPER_EVIDENCE_STOP_RULE_ENABLED=true` | `apply_stage.sh S3` |

Přechody jen dopředu S1 → S2 → S3, nejvýše jeden přechod za běh smyčky.
S3 je konečný stav smyčky.

## Pravidla (vstup: poslední řádek `/opt/cryptomaster_research/verdict.log`)

**S1** — čeká na `DECISION_READY` (n ≥ 100 v ADAPTIVE i CONTROL), nejpozději do 2026-11-09.

1. `SELECTION_EFFECT_POSITIVE` a `ADAPTIVE_POSITIVE` → GOAL_CANDIDATE: beze změny, notifikace.
2. `SELECTION_EFFECT_POSITIVE` bez `ADAPTIVE_POSITIVE` → beze změny, dokud ADAPTIVE n < 300;
   pak, pokud stále není `ADAPTIVE_POSITIVE`, → S2.
3. `SELECTION_EFFECT_NOT_SHOWN` → S2.
4. `SELECTION_EFFECT_NEGATIVE` → S3.
5. Termín 2026-11-09 bez `DECISION_READY` → S2.

**S2** — hodnotí se jen obchody otevřené po přechodu (`since_override`); termín 21 dní od přechodu.

1. `total_budget=STOP_NO_EDGE` → S3.
2. `ADAPTIVE_POSITIVE` a `total_lower > 0` → GOAL_CANDIDATE: beze změny, notifikace.
3. Termín bez bodu 2 → S3.

**Kdykoli:** `total_lower > 0` při `total_n ≥ 100` → GOAL_CANDIDATE, beze změny, notifikace.

## Bezpečnostní meze

- PAPER only. `apply_stage.sh` ověří `TRADING_MODE=paper_train`, vypnuté REAL příznaky
  a vlastní validátory bota (`paper_source_learning.validate_config`,
  `paper_neural_context.validate_config`) **před** zápisem.
- Restart jen při nule otevřených pozic (čeká max. 30 min, jinak přeskočí).
- Po restartu: READY značka do 10 min, služba aktivní 60 s, žádný Traceback →
  jinak automatický rollback na předchozí drop-in a notifikace operátorovi.
- Nikdy: změna kódu bota, TP/SL, nákladů, symbolů, REAL příznaků, deploy kódu.
- Ruční rollback: smazat `/etc/systemd/system/cryptomaster.service.d/zzzzzzzzz-auto-learning-stage.conf`,
  `systemctl daemon-reload && systemctl restart cryptomaster`, smazat
  `/opt/cryptomaster_research/{stage,since_override}`.

## Soubory

- `deploy/research_eval/` — `run_eval.sh` (časovač 05:47/17:47 UTC), `apply_stage.sh`, unit soubory.
- Server: `/opt/cryptomaster_research/{verdict.log,stage.log,stage,since_override,DECISION_READY,latest/}`.
- Lokálně: `_workspace/autonomy/LOOP.md` (postup jednoho běhu), `_workspace/autonomy/state.json`.
