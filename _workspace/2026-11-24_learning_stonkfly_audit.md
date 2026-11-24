# Revize rozhodování a učení se Stonkfly — 2026-11-24

## Rozsah a zdroje

Lokální forenzní čtení dosažitelné cesty `start.py` → `bot2/main.py` a
relevantních modulů; žádné SSH, změna konfigurace, checkpointu, runtime DB,
obchodu ani produkčního kódu. Provozní hodnoty jsou převzaty z
`docs/OPERATING_STATE.md` a `_workspace/stonkfly_eval_20261123/REPORT.md`;
jejich aktuální stav na serveru dne 24. 11. je **NOT_VERIFIED**. Repo je
záměrně dirty a server běží ze souborových manifestů, takže lokální kód není
automaticky totožný s produkčním.

## Skutečná cesta

```
Binance WS → event_bus → live quote / completed candle cache
  → p0_8_plus_shadow_evaluator.evaluate_symbol()
    → native strategy candidates
    → signal_router: validace → cost → P0/evidence budget
      → paper_source_learning (vč. volitelného Stonkfly context bucketu)
      → risk
  → p0_8_plus_live_pipeline (jediný vlastník PAPER entry)
  → paper_trade_executor → durable close journal → closed_trades SQLite
    → learning_monitor + paper_adaptive_learning
    → V5 outbox / Firebase jako projekce a telemetrie

Stejné dokončené BTC svíčky → Stonkfly paired frozen/plastic worker
  → dvě shadow prediction → centrální signal_router s tvrdým shadow invariantem
  → lokální shadow evidence + price trajectory (OBSERVE)
  → případně čerstvý frozen neural context pro native BTC candidate
```

Důkazy: `bot2/main.py:1724–1725`,
`src/services/p0_8_plus_shadow_evaluator.py:331–410`,
`src/services/p0_8_plus_live_pipeline.py:283–371,384–443`,
`src/services/signal_router.py:223–400`,
`src/services/stonkfly/runtime.py:198–216,339–341,376–489`,
`src/services/paper_trade_executor.py:3350–3560`.

### Co se dnes skutečně učí

1. `paper_source_learning.py:290–338,382–444` čte dokončené obchody z
   `closed_trades` pouze do času rozhodnutí. Pro kontext/profil spočte vážený
   post-cost průměr s half-life 16 closes, shrinkage prioru a z něj
   pravděpodobnost přijetí. Stabilní hash drží stejné přiřazení při retry.
   Kontrolní rameno a probe jsou oddělené. Konfigurace v
   `docs/OPERATING_STATE.md:24` uvádí `PAPER_LEARNING_CONTROL_FRACTION=1.0`:
   odhad se může logovat, ale adaptivní `HOLD` se v tomto režimu nepoužije.
   Cost, P0, frekvenční limit a risk přesto dále odmítají.
   Trénovací řádky jsou tedy **vybraná podmnožina** kandidátů, nikoli náhodný
   vzorek všech příležitostí; pro nový neurální readout jsou nutná samostatně
   definovaná shadow outcome data a kontrola selection bias.
2. `paper_trade_executor.py:3350–3560` nejdřív trvale uloží close do
   journalu a promítne ho do cache, pak volá zpětné learning hooks.
   `learning_monitor.update_from_paper_trade()` a
   `paper_adaptive_learning.record_close()` dostávají jen eligible uzavření.
   Legacy hook batch není jedna transakce: při nejasném částečném provedení
   zůstává journal `uncertain` a automaticky se neslepě neopakuje. Firebase
   outbox není autoritativní vstup do `paper_source_learning`.
3. Stonkfly se nyní **neučí z výsledku PAPER obchodu**. `runtime.py:198–200`
   odmítá live reward režim; `runtime.py:339–341` odesílá do workeru vždy
   `"none"`; `paired_backend.py:60–68,221–226` také vynucuje
   `reward_mode=disabled` a jiné reinforcement odmítne. `research.py:128–170`
   umí čistě offline přiřazení podle `decision_id`, ale live cesta jej nevolá
   a současný paired strategy ID ani není v jeho allowlistu.
   Pinned `stonkfly/neural/controller.py:26–45,85–93` počítá KC aktivitu a
   obchodní label z různých neuronálních výstupů. I prokázaná změna
   KC→MBON vah by sama neprokázala změnu DNp20 decoderu nebo obchodní edge.
4. `paper_neural_context.py:135–216,263–282` pro native BTC kandidáta
   přebírá pouze **frozen** člen potvrzeného páru, po kontrole čerstvosti,
   ceny, hashů a zdroje. Kontext vytváří oddělený bucket a metadatové tagy;
   nepřidává Stonkfly jako autora native obchodu. `read_outcomes()` stále
   filtruje native `learning_source`. Zisk/ztrátu BTC obchodu s přítomným
   neural context nelze označit za výsledek Stonkfly rozhodnutí.
5. `p0_8_plus_live_pipeline.py:384–431` při novém neurálním páru budí
   běžný BTC tick. Stonkfly tedy může změnit **čas/četnost** vyhodnocení BTC,
   přestože při CONTROL=1.0 nemění adaptivní admission. Tento vliv musí mít
   při hodnocení vlastní kohortu a kontrolu proti scheduleru bez neural wake.

### Výsledek dosavadní evidence

- Podle `_workspace/stonkfly_eval_20261123/REPORT.md` je všech **20 038**
  uložených labelů BUY. Frozen má KC_spikes=0 a changed_edges=0. To
  dokazuje konstantní aktuální výstup, **nikoli** příčinu uvnitř rendereru,
  senzorového mapování, connectomu či decoderu. Tyto čtyři příčiny z
  agregátů rozlišit nelze.
- Na 9 659 nezastaralých 10min trajektoriích vyšel při živé geometrii
  TP/SL a 9bps nákladu průměr −9,33bps/obchod, denní bootstrap 95%
  [−9,73; −8,95], WR 19,3 %. Náklad 9bps je podle předchozího nákladového
  auditu pro skutečný produkt spíš nízký; zde se neměnil. Výsledek se týká
  této sekvence, horizontu a simulace, ne všech možných modelů.
- Korelace `difference_hz` a `gate_spikes` s budoucím pohybem byla v obou
  chronologických polovinách blízko nule; 94 % spadlo do jediného bucketu.
  Mezi 43 native BTC obchody označenými neural contextem nebyl prokázaný
  zisk ani kauzální přínos (report: −6,76bps, WR 20,9 %).
- Samostatný předregistrovaný C1 nad native learnerem skončil
  `CONTRARIAN_NOT_SHOWN`, 1 000 obchodů; lift −1,58bps a intervaly zahrnují
  nulu (`docs/OPERATING_STATE.md:51–64`). Reset dashboardové výkonnostní
  epochy 23. 11. nemazal obchody ani učení (`:30–49`).

## Nálezy a dopad

| Priorita | Nález | Dopad |
| --- | --- | --- |
| P1 | Konstantní BUY a nulová aktivita KC ve frozen výstupu | Signál aktuálně nerozlišuje směr; bez diagnostiky není důvod přidat mu PAPER execution. |
| P1 | Live paired plastic nedostává přiřazený reward | Název plastic neznamená, že se z obchodních výsledků učí; změny vah a mechanismus jsou zatím nepotvrzené. |
| P1 | Kontextový BTC obchod není přímý Stonkfly trade | P/L tohoto obchodu nesmí bez kauzálního přiřazení vyvolat neurální reinforcement. |
| P1 | `source_signature()` hashuje všechny `src/services/stonkfly/*.py` | I změna pouze `benchmark.py` změní checkpoint identity; při příštím restartu `CheckpointStore.load()` odmítne starý checkpoint a Stonkfly se fail-closed deaktivuje. Diagnostiku držet mimo tento balík nebo připravit výslovně reviewovanou migraci/verzi checkpointu. |
| P2 | CONTROL=1.0 a 94 % v jednom neural bucketu | V současném sběrném režimu se neurální bucket testuje jako metadata, nikoli jako zlepšení rozhodování. |
| P2 | Neural wake přidává BTC vyhodnocení | Případný rozdíl v počtu/výsledku obchodů může být účinek načasování, nikoli informace neuronů. |
| P2 | `OBSERVE` ukládá cenovou trajektorii, nikoli dokončený Stonkfly obchod | Shadow ekonomika vyžaduje explicitní offline, nákladově konzistentní evaluator a jednoznačnou semantiku BUY/SELL. |
| P2 | Native learner vidí pouze uzavřené a předem filtrované PAPER obchody | Učení readoutu na této populaci bez shadow kontrol by zaměnilo selekci cost/P0/risk s prediktivní silou neuronů. |
| P2 | Renderer min–max škáluje 100 cen do jediného 320×180 profilu | Absolutní amplituda mizí; vliv na konstantní BUY je **NOT_VERIFIED**. Profil neladit na stejném testu. |

## Doporučené přepracování bez vypnutí Stonkfly

**Fáze 1 — prokázat, kde se ztrácí informace.** Nechat současný proces i
shadow párování běžet. Nad *kopií* historických dokončených vstupů, mimo
4GB produkční server nebo ve schváleném okně bez souběžné druhé instance,
spustit přesně stejný model na rostoucím, klesajícím, plochém a zrcadleném
grafu. Zapsat hash snímku, fotoreceptorovou aktivitu, KC, gate, levé/pravé
DNp20, changed_edges a decoder label. Ověřit model/data/checkpoint hash.
Příčina konstantního BUY se musí lokalizovat před změnou thresholdů. Pokud
senzor nereaguje, opraví se adaptér; pokud reaguje, ale KC ne, diagnostikuje
se mapování a neural dynamics; pokud reaguje i decoder, chyba je v live
distribuci/vstupu. Každá změna znamená novou verzovanou kohortu.
`src/services/stonkfly/config.py:162–166` hashuje všechny `.py` v balíku a
`checkpoint.py:66–74` vyžaduje shodu identity. Z toho plyne, že i čistě
diagnostické změny uvnitř balíku ohrožují obnovení živého checkpointu;
preferovaný diagnostický kód patří mimo něj.

**Fáze 2 — pravdivá outcome evidence.** Pro každý Stonkfly shadow decision
držet neměnné `decision_id`, source/version, symbol, observation/decision
čas, frame/input/checkpoint hash a raw scalars. Z existující price trajectory
offline spočítat hypotetický exit podle existujícího profilu a *stejného*
cost modelu; oddělit frozen/plastic i historické/live kohorty. Native trade
context zůstává jen kontextem. Pokrytí trajektorie, bid/ask a funding označit;
bez nich `NO_DATA` nebo konzervativní scénář, nikoli předstíraný přesný P/L.

**Fáze 3 — learning experiment.** Nejdříve ověřit, že diagnostika přináší
proměnlivé neurální features. Na uzavřených, chronologicky oddělených datech
otestovat malý kalibrovaný readout těchto features jako *shadow* kontext pro
stávající admission. To je učení readoutu, nikoli connectomu. Samostatně lze
zkoumat synaptickou plasticitu s přesně jedním přiřazeným rozhodnutím a
výsledkem; časový odstup od původního neurálního stavu vyžaduje explicitní
credit-assignment/replay protokol. Neaplikovat P/L native obchodu automaticky
na poslední Stonkfly tick. Frozen, plastic, shuffled reward, reset state,
random-frequency, always-BUY a flat musejí mít stejné vstupy, náklady a
hodnoticí okna. Nový reward/readout znamená nové strategy/version a evidence
bucket; nic se nepřipojuje k historické P0 kvalifikaci.

**Fáze 4 — teprve po validaci zvažovat účinek na admission.** Jeden předem
daný OOS nebo walk-forward test musí ukázat přínos neural features proti
stejně časovanému price-only/always-BUY baseline *po realistických nákladech*.
Vyhodnotit i latency, regimes, signal transitions, WR/PF/net P/L a nejistotu
po dnech. Není-li edge, výsledkem je `NO EDGE`; Stonkfly může zůstat
výzkumnou komponentou, ale nesmí měnit P0 nebo execution. Případná pozdější
PAPER admission používá výhradně existující router, P0, budget, risk a
executor; REAL zůstává nemožný.

## Ověření a otevřené meze

- Testy původního review zadání: 177 passed, 17 skipped, 1 warning;
  `PROTECTED_SAME`.
- Živá konfigurace, hodnoty KC pro plastic, skutečný dataset/inference na
  kontrolních grafech a soulad lokálních bajtů se serverem: **NOT_VERIFIED**.
- Bez diagnostiky nelze slíbit, že přepracovaná verze získá prediktivní edge
  ani kladné P/L. Upstream sám uvádí, že ziskové učení nebylo prokázáno:
  https://github.com/nftechie/stonkfly/blob/main/docs/model.md
- Implementační zadání pro Claude:
  `docs/codex_prompts/CLAUDE_STONKFLY_LEARNING_REWORK_2026-11-24.md`.
