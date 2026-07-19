# CryptoMaster HF-Quant 5.0 — Externí audit, kolo 6

**Předmět:** nezávislé ověření refutace maker execution a rozhodnutí o osudu DEV_FADE  
**Auditovaný commit:** `0e46810daa3bccb361d6d213d60bf4e0fb5a3c0e`  
**Datum:** 19. 7. 2026  
**Režim:** PAPER only  
**REAL trading:** **ABSOLUTNÍ NO-GO**

---

# 0. Konečný verdikt

# **C) REFUTACE JE METODICKY VADNÁ / PŘÍLIŠ ŠIROKÁ**

Současný model dostatečně dokazuje pouze toto:

> **DEV_FADE není životaschopný jako okamžitý taker při přibližně 18bps round-trip nákladu a není životaschopný ani v konkrétním zjednodušeném „midpoint-touch maker entry → exit v původním signal horizon“ modelu.**

Nedokazuje však obecné tvrzení:

> **„Žádná maker/passive/hybrid execution cesta DEV_FADE nemůže fungovat.“**

Hlavní důvody:

1. maker „fill“ je odvozen z **midpointu**, nikoli z executable bid/ask, aggTrade nebo queue dat;
2. model nepracuje s **časem fillu**, order TTL/cancel pravidlem ani holding horizon od fillu;
3. 60/40 split není purged — silně překrývající se forward dráhy sdílejí stejné budoucí tick období;
4. observation dataset není totožný s množinou obchodů, které by skutečně prošly všemi entry/cap/EV gaty;
5. recorder může označit předčasně flushnutou dráhu jako `data_quality=ok` jen podle počtu ticků, bez ověření časového pokrytí celého horizontu;
6. 97,6 % vzorku je BULL_TREND, 94 % ETH a skutečný RANGING má jen 47 řádků;
7. PR #101 byl po merge označen reviewerem P1 právě kvůli midpoint-fill modelu; nález není v commitu `0e46810` opraven.

## Provozní rozhodnutí

```text
Aktuální DEV_FADE paper execution: NO-GO
Aktuální taker cesta: RETIRE
Aktuální midpoint-touch maker model: NO-GO jako deploy podklad
Trvalé vědecké „DEV_FADE je definitivně mrtvý“: NEPROKÁZÁNO
Další actual paper trades: NO-GO
Jedna omezená oprava execution modelu + doplnění dat: GO S PODMÍNKOU
REAL trading: ABSOLUTNÍ NO-GO
```

Prakticky doporučuji **odstavit současnou implementaci DEV_FADE a pivotovat výzkum**, nikoli tvrdit, že byla definitivně vyvrácena celá třída mean-reversion signálu.

---

# 1. Důkazní omezení

Staticky byly ověřeny:

- `scripts/maker_fill_model.py`,
- `src/services/shadow_excursion_recorder.py`,
- `src/services/market_stream.py`,
- `src/services/signal_generator.py`,
- `src/services/paper_trade_executor.py`,
- `scripts/e1_e4_counterfactual.py`,
- workflow `hetzner-run-maker-model.yml`,
- PR #101 a jeho reviewer komentáře,
- konzultační brief a auditní změnový log.

Původní artefakt:

```text
maker-model-result-1
```

ani úplný shadow SQLite/export nebyl v tomto chatu přiložen a přes dostupný connector nebyl stažitelný. Nemohl jsem proto nezávisle řádkově přepočítat hodnoty:

```text
E=2 adverse selection −3,9 bp
E=4 adverse selection −4,8 bp
E=6 adverse selection −6,2 bp
OOS −0,26 / −0,09 / −1,08 bp
```

Ověřil jsem matematiku kódu, algebraické sanity checks a metodologii. Přesná čísla jsou v tomto reportu označena jako **poskytnutá artefaktovým souhrnem**, nikoli jako nezávisle reprodukovaná.

---

# 2. Odpovědi na metodické otázky §3.1

## 2.1 Fill iff `min_low_bps <= -E`

# **NE — není to korektní model skutečného maker fillu**

Recorder dostává cenu:

```python
mid = (bid + ask) / 2
```

a ukládá directional path z tohoto midpointu.

Maker model pak považuje limit za vyplněný, pokud:

```python
min_low <= -E
```

Midpoint touch však neprokazuje:

- že BUY limit dosáhl best ask / sell trade,
- že SELL limit dosáhl best bid / buy trade,
- že na dané úrovni proběhl obchod,
- že se spotřebovala fronta před naším příkazem,
- že se vyplnila celá velikost.

PR #101 dostal přesně k tomuto bodu reviewer nález **P1**.

### Dopad

Nejde jen o drobnou nepřesnost fill rate. Chybné rozdělení na:

```text
filled / unfilled
```

mění současně:

- fill rate,
- conditional horizon return,
- adverse-selection gap,
- unconditional expectancy,
- walk-forward výběr `E*`.

### Co je současný model

Lze jej označit pouze jako:

```text
midpoint-touch counterfactual
```

nikoli:

```text
maker-fill counterfactual
```

### Potřebná data

Minimálně:

- bid,
- ask,
- timestamp,
- aggTrade price/side/volume,
- limit price,
- time-in-force,
- volitelně depth/queue proxy.

Přijatelný konzervativní fill rule:

### BUY

```text
trade_price <= buy_limit
a agresor je SELL
a kumulovaný volume přes limit překročí queue-ahead + order size
```

### SELL

analogicky opačně.

Bez queue dat je možné použít více scénářů:

```text
optimistic touch
base traded-through
conservative queue-adjusted
```

Verdikt musí být stabilní ve všech.

---

## 2.2 Adverse-selection metrika

Použitá metrika:

```text
mean(F | fill) − mean(F | all)
```

má **správné znaménko**:

- záporná hodnota znamená, že dotčená/fill podmnožina má horší horizon výsledek než celý vzorek.

Je to užitečná deskriptivní selection metrika.

### Není však sama o sobě execution PnL

Pro maker benefit je nutné vyhodnotit:

```text
entry improvement E
+ return po skutečném fillu
− fee
− exit cost
− queue/partial-fill penalty
− opportunity/capital cost
```

Současná velikost adverse selection je navíc podmíněna chybnou midpoint-touch klasifikací.

# Verdikt

```text
definice: VALIDNÍ
vstupní fill labels: NEVALIDOVANÉ
reportované velikosti: NEPOTVRZENÉ
```

---

## 2.3 Unconditional expectancy s unfilled = 0

# **ANO — per signal opportunity je to správně**

Nevyplněný příkaz skutečně vytvoří:

```text
0 PnL
```

Není nefér započítat zmeškané reverze jako nulu; maker strategie je skutečně nezachytila.

Musí se však reportovat oba pohledy:

```text
expectancy per signal opportunity
expectancy per filled trade
fill count
fill rate
PnL per unit času
capital/exposure utilization
```

### Zásadní omezení současného datasetu

Signály mají debounce přibližně 15 sekund, recorder horizon je defaultně 300 sekund. Pro jeden symbol tak může existovat mnoho překrývajících se pozorování.

Všechny nelze automaticky považovat za současně obchodovatelné nezávislé příležitosti.

Unconditional expectancy na každý raw signal proto není totéž jako realizovatelný portfolio PnL.

---

## 2.4 Walk-forward

### Co je správně

Kód:

1. řadí řádky podle `signal_ts_ms`,
2. používá prvních 60 % jako train,
3. vybere `E*`,
4. posledních 40 % vyhodnotí jednou.

Přímé použití test výsledku při výběru `E*` v kódu nevidím.

### Co je nesprávně označeno

Nejde o plný walk-forward. Je to:

```text
single chronological holdout
```

### Leak přes překrývající se horizonty

Pokud jsou signály od sebe 15 sekund a dráha trvá 300+ sekund:

- poslední train observations používají tick data po začátku prvních test observations,
- train a test sdílejí stejné market path období,
- observations uvnitř testu jsou silně korelované.

Split podle signal start timestampu tedy není čistě nezávislý.

### Povinná oprava

Použít:

- purge/embargo nejméně jeden celý max horizon kolem splitu,
- blocked walk-forward po časových blocích,
- cluster bootstrap podle market episode / hodiny / dne,
- ne row-wise bootstrap.

### Stupně volnosti

Explicitně se ladí jen `E`, ale implicitně jsou pevně zvoleny:

- horizon,
- TIF nekonečný do horizon,
- exit v původním signal horizon,
- cost pro selection,
- offset ladder,
- signal admission population,
- midpoint fill rule.

Tvrzení „jediný stupeň volnosti“ je proto příliš silné.

---

## 2.5 Sanity `taker@18 = Fmean − 18`

# **ANO — algebraicky potvrzeno**

Kód počítá:

```python
mean(F - cost)
```

Při konstantním nákladu platí přesně:

```text
mean(F − 18) = mean(F) − 18
2,05 − 18 = −15,95 bp
```

Tento test potvrzuje aritmetiku taker baseline.

Nepotvrzuje:

- správnost vstupních drah,
- správnost horizon,
- fill model,
- nezávislost observations,
- režimovou generalizaci.

---

# 3. Nové blokující metodické nálezy

## 3.1 Midpoint není executable price — P1

`market_stream._dispatch()` publikuje jako `price` midpoint. Recorder z něj počítá signed favorable bps. Maker model z midpoint low odvozuje fill.

To je přímá modelová chyba pro maker execution.

## 3.2 Model ignoruje čas fillu

Maker fill může nastat:

- 1 sekundu po signálu,
- 299 sekund po signálu.

V obou případech se PnL počítá vůči stejnému původnímu horizon close.

Pozdní fill má výrazně méně času na reverzi.

Realistický model potřebuje alespoň dvě předem registrované varianty:

```text
A: exit při původním signal expiry
B: fixní hold od okamžiku fillu
```

Bez toho refutace testuje pouze jednu konkrétní exit politiku.

## 3.3 Chybí Time-in-Force / cancel model

Současný příkaz leží až do konce horizon.

Rozumná maker/hybrid politika může být:

```text
post-only na 1 / 3 / 5 / 10 / 30 s
pak cancel
případně taker jen pokud signál stále splňuje předem definovaný edge gate
```

Krátké TIF může odmítnout pozdní, silně adverse fills.

To neznamená, že taková politika bude zisková. Znamená to, že současný model ji netestuje a nemůže ji vyvrátit.

## 3.4 Data-quality kontrola neověřuje horizon coverage

Recorder označí observation jako `ok`, pokud:

```text
sample_count >= horizon_s
```

Neověří, že:

```text
last_second_offset dosáhl konce horizon
```

Při vysoké tick frekvenci může observation nasbírat mnoho ticků během kratší doby, být při restartu `flush_all()` předčasně uzavřená a přesto získat `data_quality=ok`.

Maker model:

- nenačítá `horizon_ms`,
- nekontroluje skutečný path duration,
- nekontroluje poslední second offset proti horizon.

Po několika provozních restartech může dataset obsahovat různé nebo předčasně ukončené forward horizons.

### Povinná oprava

Observation přijmout jen pokud:

```text
completed_normally = 1
last_second_offset >= floor(horizon_ms / second_ms) − tolerance
end_ts_ms − signal_ts_ms >= horizon_ms − tolerance
```

Shutdown flush má mít samostatný stav:

```text
partial_shutdown_flush
```

a nesmí být součástí hlavní analýzy.

## 3.5 Dataset není množina skutečně executable trades

Observation se spustí v `_on_signal_created()` ještě před voláním `open_paper_position()`.

Tím obchází další entry rozhodnutí:

- weak EV gate,
- secondary segment profitability gate,
- time gate,
- exposure caps,
- per-symbol cap,
- max-open cap,
- další position construction validace.

Dataset tedy odpovídá spíše:

```text
P0-routable signal candidates
```

než:

```text
trades, které by skutečně byly otevřeny
```

To může výrazně zředit nebo změnit edge.

### Povinný kontrakt

Každá observation musí mít:

```text
signal_edge
raw_candidate
p0_admitted
would_pass_open_paper_position
blocked_reason
exposure_cap_state
position_policy_version
```

Analýza musí oddělit:

```text
raw signal edge
executable policy edge
```

## 3.6 Překrývající se observations a nadhodnocené N

Při 15s debounce a 300s horizon může mít ETH přibližně 20 souběžných forward observations.

`n=9305` proto není `9305` nezávislých pokusů.

Potřebné:

- effective sample size,
- block clustering,
- one-signal-per-symbol-per-horizon sensitivity,
- embargoed split,
- confidence interval clusterovaný po času.

## 3.7 OOS zero-cost tvrzení je příliš široké

Walk-forward vybere `E*` při cost = 3 bp a následně stejný `E*` reportuje při cost = 0.

Výsledek:

```text
test −0,09 bp při cost 0
```

znamená:

> Offset vybraný pro 3bps model byl na testu záporný i po odstranění nákladu.

Neznamená automaticky:

> Všechny offsety jsou OOS záporné při zero cost.

Pro toto tvrzení je nutný:

- samostatný předem definovaný zero-cost selection,
- nebo OOS tabulka všech offsetů označená jako diagnostická, nikoli znovu optimalizovaný verdict.

## 3.8 OOS verdict nemá minimum filled observations

Reviewer PR #101 zachytil P2:

- pozitivní unconditional OOS expectancy může teoreticky vzniknout z jednoho fillu,
- model nekontroluje minimální počet fills,
- nepočítá uncertainty CI.

Pro současný negativní výsledek to není přímý false-negative bug, ale ukazuje, že verdict framework není kompletní.

---

# 4. Data adequacy a režimová generalizace

Reported dataset:

```text
n = 9305
BULL_TREND = 9084
QUIET_RANGE = 174
RANGING = 47
ETH ≈ 94 %
BEAR ≈ 0
```

Range-like součet:

```text
QUIET_RANGE + RANGING = 221
```

Není správné jej označit jako 221 čistých RANGING observations.

## Je adverse selection strukturální?

Směr mechanismu je obecný:

> pasivní fade entry se plní častěji při pokračování pohybu proti signálu.

Velikost tohoto efektu však není univerzální.

V čistém mean-reverting range režimu může:

- adverse pokračování být kratší,
- reversion po fillu být silnější,
- pozdější maker entry zlepšit R:R,
- fill-time distribution být jiná.

Z BULL-heavy vzorku proto nelze přenést přesnou velikost selection gapu na RANGING.

## Požadavek před definitivním regime verdict

Ne raw řádky, ale časově efektivní observations:

```text
RANGING: nejméně 500 purged/non-overlapping observations
QUIET_RANGE: nejméně 500
BEAR_TREND: nejméně 500
BULL_TREND: nejméně 500
```

Dále:

```text
nejméně 20 oddělených regime episodes na hodnocený režim
nejméně 30 kalendářních dní
nejméně 3 symboly s ≥150 observations
žádný symbol >50 % datasetu
ETH-only závěr se nesmí vydávat za universe závěr
```

Při menším počtu lze segment označit pouze:

```text
exploratory / insufficient
```

---

# 5. Co přesně současná data dovolují uzavřít

## Potvrzeno

1. Při taker round-trip cost 18 bp a gross horizon mean kolem +2,05 bp je strategie ekonomicky hluboce záporná.
2. Aktuální TP/SL/TIMEOUT paper implementace je nefunkční a má zůstat vypnutá.
3. Jednoduché čekání na midpoint adverse touch bez TIF a s exit při původním horizon nevytváří prokázanou OOS edge.
4. Současná maker hypotéza není připravena k paper forward testu.
5. REAL trading je absolutní NO-GO.

## Nepotvrzeno

1. Že skutečný maker fill model má stejné fill labels.
2. Že krátké TIF/cancel maker provedení je záporné.
3. Že maker-then-conditional-taker hybrid je záporný.
4. Že DEV_FADE nemůže fungovat v RANGING/QUIET.
5. Že celý 7symbolový universe je vyvrácen ETH/BULL vzorkem.
6. Že `n=9305` představuje 9305 nezávislých observations.
7. Že všechny řádky mají úplný stejný horizon.
8. Že dataset odpovídá skutečným obchodním admission pravidlům.

---

# 6. Povinný opravený experiment

## Fáze M1 — opravit data

Recorder musí přidat:

```text
bid
ask
spread_bps
agg_trade_price
agg_trade_side
agg_trade_volume
depth/queue proxy
edge
admission decision
blocked reason
horizon_ms
normal_completion
actual_path_duration_ms
```

## Fáze M2 — executable fill scenarios

Pro každý maker offset:

### Optimistic

```text
quote touch
```

### Base

```text
executable side crossed + qualifying aggTrade
```

### Conservative

```text
traded-through + queue-ahead/partial-fill haircut
```

Výsledek musí být stabilní alespoň v base a conservative scénáři.

## Fáze M3 — předem registrované execution policies

Maximálně omezená mřížka:

```text
offset E: 1, 2, 3, 4, 6 bp
TIF: 1, 3, 5, 10, 30 s
exit clock:
  A) původní signal expiry
  B) fixní horizon od fillu
```

Hybrid:

```text
maker do TIF
potom cancel
taker pouze pokud předem zmrazený signal-validity gate stále platí
```

Bez průběžného ladění podle testu.

## Fáze M4 — purged nested walk-forward

- chronological train,
- validation pro výběr policy,
- purge + embargo alespoň max horizon,
- untouched test,
- více rolling folds,
- cluster bootstrap po časových blocích/regime episodes.

## Fáze M5 — realistické costs

Reportovat:

```text
maker fee/rebate
taker exit fee
spread
slippage
partial-fill
cancel/no-fill
latency
```

Testovací cost scenarios musí vycházet z konkrétního venue/tier, ne z abstraktního `0 / 3 / 18`.

---

# 7. GO / NO-GO rozhodnutí

| Položka | Verdikt | Kdo |
|---|---|---|
| Pokračovat v aktuálním DEV_FADE paper tradingu | **NO-GO** | operátor ponechá vypnuté |
| Aktivovat maker DEV_FADE podle `maker_fill_model.py` | **NO-GO** | zakázáno |
| Trvale označit celou DEV_FADE signal class za vyvrácenou | **NO-GO** | důkaz nestačí |
| Retire současnou konkrétní implementaci | **GO** | operátor / dokumentace |
| Opravit recorder na executable quotes/trades | **GO S PODMÍNKOU** | autonomní agent + reviewer |
| Doplnit TIF/fill-time/purged model | **GO S PODMÍNKOU** | autonomní agent + independent quant review |
| Pokračovat observation-only sběrem | **GO** | operátor; žádné pozice |
| Dosbírat RANGING/QUIET/BEAR | **GO** | observation only |
| Jeden další actual paper forward test | **NO-GO nyní** | až po validním OOS GO |
| REAL trading | **ABSOLUTNÍ NO-GO** | bez výjimky |

---

# 8. Podmínky pro poslední rozhodnutí retain/retire

Po opravené metodice lze DEV_FADE ponechat k jedinému PAPER forward testu jen pokud:

```text
OOS PF >= 1.20
net expectancy > 0
doporučená rezerva >= +2 až +3 bp/fill po realistických nákladech
cluster-bootstrap 95% CI lower > 0
minimum OOS fills >= 200 pro vybranou policy
fill rate má interval spolehlivosti
výsledek stabilní alespoň ve 2 režimech nebo explicitně regime-gated
žádný symbol >50 % zisku
výsledek přežije conservative fill scenario
```

Pokud opravený base/conservative model selže:

```text
RETIRE DEV_FADE definitivně
```

Pokud data adequacy nebude dosažena do předem omezeného research budgetu, například:

```text
30 dní nebo 500 validních range-like effective observations
```

doporučuji strategii archivovat a pivotovat bez dalšího sunk-cost prodlužování.

---

# 9. Explicitní odpověď na volbu A/B/C

# **VOLBA C — REFUTACE VADNÁ**

Ne proto, že by současná data ukazovala ziskovou strategii.

Naopak:

```text
současná execution = ztrátová
současná maker implementace = neprokázaná
actual trading = NO-GO
```

Volba C platí proto, že load-bearing maker fill model používá midpoint touch jako fill a netestuje zásadní execution parametry. Nemůže proto legitimně podporovat široký závěr:

```text
maker execution nepomáhá za žádných podmínek
```

## Praktický manažerský závěr

```text
Retire current DEV_FADE implementation: ANO
Retire all future research on the hypothesis immediately: NE
Povolit jeden omezený corrected-model audit: ANO
Pokud neprojde: definitivně archivovat a pivotovat
```

---

# 10. Bezpečnostní stanovisko

Tento audit nemění předchozí safety závěry.

```text
PAPER only
žádný actual paper forward test nyní
žádný maker deployment
žádný live order
REAL = absolutní NO-GO
```

---

# 11. Finální závěr auditora

> **Refutace maker execution není v současné podobě dostatečně důvěryhodná pro definitivní vědecké „retire DEV_FADE“. Nejdůležitější klasifikace fillu používá midpoint, nikoli executable quote/trade data; model ignoruje fill time a TIF, split není purged proti překrývajícím se horizons, dataset nemusí odpovídat skutečně admissible obchodům a režimové pokrytí je extrémně jednostranné.**
>
> **Současnou konkrétní DEV_FADE implementaci je však racionální odstavit: taker edge je při 18bps nákladu jasně neobchodovatelná a stávající maker model neposkytuje žádný podklad k nasazení. Povolil bych pouze jeden časově a rozsahem omezený corrected execution audit v observation-only režimu. Pokud executable quote/trade + TIF + purged OOS model nedosáhne PF ≥1,20 a kladné expectancy v base i conservative fill scénáři, DEV_FADE definitivně archivovat a pivotovat k jiné třídě signálu.**
