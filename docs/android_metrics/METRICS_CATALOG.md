# CryptoMaster Android - Katalog Metrik

**Verze:** 1.0  
**Aktualizováno:** 2026-05-19  
**Cílová aplikace:** Android Dashboard (read-only monitor)

---

## A. Stav Robota a Health

### BOT_STATUS
- Název v aplikaci: **Status robota**
- Krátký popis: Základní stav - běží, pozastaveno, chyba
- Proč je důležitá: Uživatel potřebuje vědět, zda bot vůbec funguje
- Typ: RAW / HEALTH
- Zdroj pravdy: bot2/main.py runtime state
- Firebase collection/doc/field: `bot_config/health/status`
- Log pattern: `[BOT_STATE]`, `ERROR`, `Exception`
- Formula: Live signal - aplikace běží vs. chyba/zastaveno
- Unit: enum
- Data type: string
- Update frequency: Real-time (event-driven)
- Recommended UI: Badge "Běží" (green) / "Paused" / "Chyba" (red)
- Priority: **P0**
- Freshness rule: Musí být aktuální do 10s, jinak zobrazit "Stale"
- Green threshold: Status == "running"
- Yellow threshold: Status == "paused" nebo heartbeat > 30s
- Red threshold: Status == "error" nebo heartbeat > 120s
- Czech tooltip: "Aktuální stav běhu robota. Pokud 'Chyba', zkontrolujte logy."
- Caveats: Aplikace může selhat bez aktualizace tohoto stavu
- Implementation notes: Vyžaduje heartbeat mechanismus

### TRADING_MODE
- Název v aplikaci: **Režim obchodování**
- Krátký popis: live_real / paper_train / paper_live
- Proč je důležitá: Uživatel musí vědět, zda bot skutečně investuje nebo pouze testuje
- Typ: RAW
- Zdroj pravdy: `src/core/runtime_mode.py` - `get_trading_mode()`
- Firebase collection/doc/field: `bot_config/trading_mode`
- Log pattern: `TRADING_MODE=`, `Mode:`
- Formula: Environment variable TRADING_MODE
- Unit: enum
- Data type: string
- Update frequency: Při startu (statické během běhu)
- Recommended UI: Large badge "Live Trading" / "Paper Training" / "Paper Live"
- Priority: **P0**
- Freshness rule: Ověřit při startu aplikace
- Green threshold: Mode == "paper_train" nebo "paper_live" (bezpečné)
- Yellow threshold: Mode == "paper_live" (simulace reálná, ale bez skutečných peněz)
- Red threshold: Mode == "live_real" (obchodování se skutečnými penězi)
- Czech tooltip: "Aktivní režim obchodování. 'live_real' = skutečné obchody!"
- Caveats: Změna vyžaduje restart bota
- Implementation notes: Přečíst při startu, cache po dobu relace

### GIT_HEAD
- Název v aplikaci: **Verze kódu (Git)**
- Krátký popis: Aktuální commit SHA
- Proč je důležitá: Identifikovat, jaká verze kódu běží (debug, odpovědnost za chyby)
- Typ: RAW
- Zdroj pravdy: `git log --oneline -1` nebo soubor s verzí
- Firebase collection/doc/field: `bot_config/git_head`
- Log pattern: `Git HEAD:`, `Commit:`
- Formula: Environment variable GIT_HEAD nebo runtime `git rev-parse HEAD`
- Unit: sha1
- Data type: string (8-40 znaků)
- Update frequency: Při startu
- Recommended UI: Malý text v header "v: abc1234"
- Priority: **P2**
- Freshness rule: Statické během běhu
- Green threshold: Odpovídá expected commit
- Yellow threshold: N/A
- Red threshold: Neznámý/prázdný commit
- Czech tooltip: "SHA posledního commitu. Pomocí pro debug."
- Caveats: Vyžaduje .git přístup nebo external config
- Implementation notes: Cachovat při startu aplikace

### UPTIME_SECONDS
- Název v aplikaci: **Doba běhu (s)**
- Krátký popis: Kolik sekund bot běží bez restartování
- Proč je důležitá: Stabilita - časté restarty signalizují problém
- Typ: DERIVED
- Zdroj pravdy: Bot start time vs. current time
- Firebase collection/doc/field: `bot_metrics/uptime_s`
- Log pattern: `Uptime:`, `Started:`
- Formula: now() - bot_start_timestamp
- Unit: seconds
- Data type: integer
- Update frequency: Každých 30s
- Recommended UI: Text "12h 34m 56s" nebo "uptime:46496s"
- Priority: **P1**
- Freshness rule: Do 60s
- Green threshold: > 3600s (>1 hodina bez restartů)
- Yellow threshold: 300-3600s (5-60 minut)
- Red threshold: < 300s (<5 minut - časté restarty)
- Czech tooltip: "Jak dlouho bot bez přerušení běží. Kratší časy = problémy?"
- Caveats: Resetuje se při restartu
- Implementation notes: Vypočítat lokálně z bot_start_ts

### LAST_HEARTBEAT_TS
- Název v aplikaci: **Poslední signal (čas)**
- Krátký popis: Timestamp poslední aktivity bota
- Proč je důležitá: Zjistit, zda je bot mrtvý (zakonzervovaný, bez aktualizace)
- Typ: RAW
- Zdroj pravdy: Event bus / Firebase health snapshot
- Firebase collection/doc/field: `bot_health/last_heartbeat_ts`
- Log pattern: `[HEARTBEAT]`, `Loop:`, `Update:`
- Formula: max(last_signal_ts, last_trade_ts, last_log_ts)
- Unit: unix timestamp (seconds)
- Data type: number
- Update frequency: Real-time
- Recommended UI: Relativní čas "před 5s", "před 2m", "offline"
- Priority: **P0**
- Freshness rule: Pokud nyní - last_heartbeat_ts > 120s, zobrazit "OFFLINE"
- Green threshold: last_heartbeat < 10s
- Yellow threshold: 10-60s
- Red threshold: > 60s (bot neodpovídá)
- Czech tooltip: "Čas poslední aktivity robota. >60s = problém!"
- Caveats: Může chybět log záznam o heartbeatu
- Implementation notes: Sledovat event bus nebo Firebase snapshot

---

## B. Health tržních dat

### MARKET_FEED_STATUS
- Název v aplikaci: **Status tržních dat**
- Krátký popis: WebSocket připojen / Fallback REST / Offline
- Proč je důležitá: Signály jsou neplatné bez aktuálních cen
- Typ: RAW / HEALTH
- Zdroj pravdy: `market_stream.py` - WebSocket connection state
- Firebase collection/doc/field: `market_health/feed_status`
- Log pattern: `[MARKET_OFFLINE]`, `[WS_RECONNECT]`, `WebSocket:`, `Fallback:`
- Formula: WS.is_connected() OR REST.is_fallback_active()
- Unit: enum
- Data type: string
- Update frequency: Real-time (při reconnectu)
- Recommended UI: Indikátor "Živě ⚡" / "Náhrada 📡" / "Offline ❌"
- Priority: **P0**
- Freshness rule: Okamžitě aktualizovat
- Green threshold: WS connected
- Yellow threshold: REST fallback active
- Red threshold: Both offline
- Czech tooltip: "Zdroj tržních cen. WS = živé, REST = náhrada, Offline = selhání."
- Caveats: Fallback může být zaostávající; offline = bez nových signálů
- Implementation notes: Naslouchat event bus `market_online` / `market_offline`

### LAST_PRICE_TICK_TS
- Název v aplikaci: **Poslední cena (čas)**
- Krátký popis: Timestamp poslední aktualizace ceny
- Proč je důležitá: Kontrola, že ceny nejsou zastarané
- Typ: RAW
- Zdroj pravdy: market_stream.py - timestamp poslední price candle
- Firebase collection/doc/field: `market_health/last_tick_ts`
- Log pattern: `Price:`, `Tick:`, `Stream:`, timestamp
- Formula: max(all price updates timestamps)
- Unit: unix timestamp (ms)
- Data type: number
- Update frequency: Každý tick (~1/sec)
- Recommended UI: Relativní čas "před 1s", "před 5m"
- Priority: **P1**
- Freshness rule: Do 10s (jinak yellow), do 60s (jinak red)
- Green threshold: < 2s
- Yellow threshold: 2-10s
- Red threshold: > 10s
- Czech tooltip: "Čas poslední ceny. >10s = tržní data zaostávají!"
- Caveats: Může se lišit per-symbol
- Implementation notes: Trackovat per-symbol s agregací

### SYMBOLS_ACTIVE_COUNT
- Název v aplikaci: **Aktivní symboly**
- Krátký popis: Počet symbolů se svěžími cenami
- Proč je důležitá: Zda bot pokrývá všechny expected symboly
- Typ: DERIVED
- Zdroj pravdy: market_stream.py - symbols with recent prices
- Firebase collection/doc/field: `market_health/active_symbols`
- Log pattern: `Active symbols:`, `Symbols:`, `Count:`
- Formula: count(symbols where last_tick_ts > now - 30s)
- Unit: count
- Data type: integer
- Update frequency: Každých 30s
- Recommended UI: Text "5/5 symboly aktivní" nebo "3/5 (2 zastaralé)"
- Priority: **P1**
- Freshness rule: Do 60s
- Green threshold: == expected_symbol_count
- Yellow threshold: 50% ≤ active < 100%
- Red threshold: < 50%
- Czech tooltip: "Kolik symbolů má aktuální ceny. Nižší = méně opportunities."
- Caveats: Může být asymetrické (BTC живě, ETH zastaralé)
- Implementation notes: Agregovat z per-symbol health

---

## C. Firebase / Kvóta

### FIRESTORE_READ_COUNT_DAY
- Název v aplikaci: **Firebase čtení (den)**
- Krátký popis: Počet Firestore read operací za posledních 24h
- Proč je důležitá: Sledovat vyčerpání denní kvóty (limit 50k)
- Typ: RAW / DERIVED (z firebase_client.py)
- Zdroj pravdy: `firebase_client.py` - _record_read() log
- Firebase collection/doc/field: `quota_metrics/reads_day`
- Log pattern: `[QUOTA]`, `reads:`, `read_count`
- Formula: sum(all read ops in last 24h)
- Unit: count
- Data type: integer
- Update frequency: Real-time (v cache na 1h)
- Recommended UI: Počitadlo "12,456 / 50,000 čtení"
- Priority: **P1**
- Freshness rule: Cache max 1h
- Green threshold: < 25,000 (50%)
- Yellow threshold: 25,000 - 40,000 (50-80%)
- Red threshold: > 40,000 (80%+)
- Czech tooltip: "Firestore čtení za 24h. Limit je 50k. Blížíme se limitu?"
- Caveats: Resetu se v půlnoc PT (09:00 GMT+2)
- Implementation notes: Čtení z `firebase_client.py` kvóta cache

### READ_QUOTA_PCT
- Název v aplikaci: **Zbytek čtení (%)**
- Krátký popis: Procento zbývající denní Firestore kvóty
- Proč je důležitá: Vizuálně vidět, jak se blížíme limitu
- Typ: DERIVED
- Zdroj pravdy: (50000 - read_count) / 50000 * 100
- Firebase collection/doc/field: Calculated field
- Log pattern: N/A (derived)
- Formula: (50000 - FIRESTORE_READ_COUNT_DAY) / 50000 * 100
- Unit: percent
- Data type: float
- Update frequency: Real-time
- Recommended UI: Progress bar s barvami (green 50-100%, yellow 20-50%, red <20%)
- Priority: **P1**
- Freshness rule: Stejné jako read_count
- Green threshold: > 50%
- Yellow threshold: 20-50%
- Red threshold: < 20%
- Czech tooltip: "Zbývající Firestore kvóta. <20% = restrikce!"
- Caveats: Nepočítá write kvótu
- Implementation notes: Jednoduchost výpočet z read_count

### QUOTA_STATE
- Název v aplikaci: **Stav kvóty**
- Krátký popis: NORMAL / WARNING / EXHAUSTED
- Proč je důležitá: Automatické varování, když je kvóta kritická
- Typ: DERIVED / HEALTH
- Zdroj pravdy: firebase_client.py - quota check logic
- Firebase collection/doc/field: `quota_metrics/state`
- Log pattern: `[QUOTA_STATE]`, `exhausted`, `degraded`
- Formula: IF read_pct < 20 OR write_pct < 20 THEN "WARNING"; IF read_pct < 5 OR write_pct < 5 THEN "EXHAUSTED"
- Unit: enum
- Data type: string
- Update frequency: Real-time
- Recommended UI: Status badge "OK ✓" / "Varování ⚠️" / "Vyčerpáno 🚫"
- Priority: **P0** (když EXHAUSTED)
- Freshness rule: Okamžitě
- Green threshold: NORMAL
- Yellow threshold: WARNING
- Red threshold: EXHAUSTED
- Czech tooltip: "Stav Firestore kvóty. EXHAUSTED = bot se zpomaluje!"
- Caveats: Může být falešné varování, pokud je čtení z cacheů
- Implementation notes: Nastavit v firebase_client.py kvóta check

---

## D. Přehled obchodů

### TOTAL_TRADES
- Název v aplikaci: **Celkových obchodů**
- Krátký popis: Počet všech uzavřených obchodů (live + paper)
- Proč je důležitá: Základní metryka úspěchu - objeme
- Typ: RAW
- Zdroj pravdy: Firebase `trades` collection - count()
- Firebase collection/doc/field: `trading_summary/total_trades`
- Log pattern: `[TRADE_CLOSED]`, `Total:`, `Trades:`
- Formula: count(trades where status == "closed")
- Unit: count
- Data type: integer
- Update frequency: Po každém uzavření obchodu
- Recommended UI: Velké číslo "127 obchodů"
- Priority: **P0**
- Freshness rule: Do 10s
- Green threshold: > 10
- Yellow threshold: 1-10
- Red threshold: 0
- Czech tooltip: "Počet kompletních obchodů. Více = déle běží."
- Caveats: Počítá se live i paper obchody dohromady
- Implementation notes: Cachovat z LearningMonitor

### CLOSED_TRADES
- Název v aplikaci: **Uzavřené obchody (live)**
- Krátký popis: Pouze live/real obchody (ne paper training)
- Proč je důležitá: Skutečný počet skutečných obchodů
- Typ: RAW
- Zdroj pravdy: Firebase `trades` collection - filter trading_mode=="live_real"
- Firebase collection/doc/field: `trading_summary/closed_trades_live`
- Log pattern: `[TRADE_CLOSED]`, `Mode: live_real`
- Formula: count(trades where status == "closed" AND mode == "live_real")
- Unit: count
- Data type: integer
- Update frequency: Po každém uzavření obchodu
- Recommended UI: Text "12 live obchodů"
- Priority: **P1**
- Freshness rule: Do 10s
- Green threshold: > 5
- Yellow threshold: 1-5
- Red threshold: 0
- Czech tooltip: "Živé obchody. Paper training se nepočítá."
- Caveats: Počet se poměřuje k times = věr obchodů není bezprostředně
- Implementation notes: Filtrovat z TOTAL_TRADES po mode

### WINRATE
- Název v aplikaci: **Úspěšnost (%)**
- Krátký popis: % obchodů s kladným PnL
- Proč je důležitá: Nejzákladnější metryka profitability
- Typ: DERIVED
- Zdroj pravdy: Firebase trades - (wins / total) * 100
- Firebase collection/doc/field: `trading_summary/winrate_pct`
- Log pattern: `Winrate:`, `WR:`, `Success%:`
- Formula: (count(trades where pnl > 0) / count(all trades)) * 100
- Unit: percent
- Data type: float
- Update frequency: Po každém obchodu
- Recommended UI: Procenta s barvou "55.2%"
- Priority: **P0**
- Freshness rule: Do 10s
- Green threshold: > 55%
- Yellow threshold: 45-55%
- Red threshold: < 45%
- Czech tooltip: "Procento vítězných obchodů. >55% je dobrý. <45% je problém."
- Caveats: Neměří velikost zisku vs ztráty (Sharpe, Sortino atd)
- Implementation notes: Počítat z closed trades

### NET_PNL_PCT
- Název v aplikaci: **Čistý zisk (%)**
- Krátký popis: Celkový zisk jako % od počátečního kapitálu
- Proč je důležitá: Skutečná profitability v čase
- Typ: DERIVED
- Zdroj pravdy: sum(all trade pnls) / initial_capital * 100
- Firebase collection/doc/field: `trading_summary/net_pnl_pct`
- Log pattern: `Net PnL:`, `Total gain:`, `Return:`
- Formula: (sum(pnl) / initial_capital) * 100 nebo (final_capital - initial_capital) / initial_capital * 100
- Unit: percent
- Data type: float
- Update frequency: Po každém obchodu
- Recommended UI: Velké číslo "+12.34%" (zelené) / "-3.21%" (červené)
- Priority: **P0**
- Freshness rule: Do 10s
- Green threshold: > 0%
- Yellow threshold: -5% do 0%
- Red threshold: < -5%
- Czech tooltip: "Čistý zisk v procentech. Negativní znamená ztráty!"
- Caveats: Nepočítá inflaci, náklady, daně
- Implementation notes: Cachovat z LearningMonitor economic health

---

## E. Otevřené pozice (live obchody)

### OPEN_POSITIONS_COUNT
- Název v aplikaci: **Otevřených pozic**
- Krátký popis: Počet aktuálně otevřených live obchodů
- Proč je důležitá: Zda bot aktivně obchoduje
- Typ: RAW
- Zdroj pravdy: Firebase `open_positions` collection - count()
- Firebase collection/doc/field: `trading_state/open_count`
- Log pattern: `[POSITION_OPEN]`, `Open:`, `Positions:`
- Formula: count(positions where status == "open")
- Unit: count
- Data type: integer
- Update frequency: Real-time
- Recommended UI: Badge "3 otevřené pozice"
- Priority: **P0**
- Freshness rule: Do 5s
- Green threshold: 1-5
- Yellow threshold: 0 (idle) nebo > 5 (over-exposed)
- Red threshold: N/A
- Czech tooltip: "Kolik obchodů aktuálně běží. 0 = bez akcí, >5 = riziko."
- Caveats: Paper obchody se počítají samostatně
- Implementation notes: Čtení z Firebase real-time listener

### Por_symbol_open_position (table)
- Pro každou otevřenou pozici:
  - symbol (BTC, ETH)
  - side (BUY/SELL)
  - entry_price
  - current_price
  - unrealized_pnl_pct
  - size_usd
  - hold_s (doba, jak dlouho otevřeno)
  - tp (take profit cena)
  - sl (stop loss cena)
  - distance_to_tp_pct
  - distance_to_sl_pct

---

## F. Historie obchodů (poslední N)

### LAST_TRADE_TS
- Název v aplikaci: **Poslední obchod (čas)**
- Krátký popis: Timestamp posledního uzavřeného obchodu
- Proč je důležitá: Vidět aktuální aktivitu
- Typ: RAW
- Zdroj pravdy: Firebase trades collection - max(exit_ts)
- Firebase collection/doc/field: `trading_summary/last_trade_ts`
- Log pattern: `[TRADE_CLOSED]`, timestamp
- Formula: max(all exit timestamps)
- Unit: unix timestamp
- Data type: number
- Update frequency: Po každém obchodu
- Recommended UI: Relativní čas "před 5m", "1h+ bez obchodu"
- Priority: **P1**
- Freshness rule: Do 30s
- Green threshold: < 60 min (aktivní)
- Yellow threshold: 60-360 min
- Red threshold: > 360 min (6+ hodin bez obchodů)
- Czech tooltip: "Čas posledního uzavřeného obchodu. Dlouhá absence = idle?"
- Caveats: Nepočítá obchody bez exitů (hanged trades)
- Implementation notes: Sledovat event bus na obchod_closed

---

## G. LearningMonitor / Stav učení

### LM_TOTAL_TRADES
- Název v aplikaci: **LM: Celkový trades count**
- Krátký popis: Kanonické počet obchodů známých LearningMonitoru
- Proč je důležitá: Zdrojová metrika pro decisions (ne stálé metrics)
- Typ: RAW
- Zdroj pravdy: `learning_monitor.py` - sum(lm_count.values())
- Firebase collection/doc/field: `learning_state/lm_total_trades`
- Log pattern: `[LM_STATE_AFTER_UPDATE]`, `trades:`, `count:`
- Formula: sum(lm_count[(symbol, regime)])
- Unit: count
- Data type: integer
- Update frequency: Po každé LM update
- Recommended UI: Text "184 trades v LM"
- Priority: **P1**
- Freshness rule: Do 10s
- Green threshold: > 100
- Yellow threshold: 10-100
- Red threshold: < 10 (cold-start)
- Czech tooltip: "Počet trades v LearningMonitor. <10 = bot se ještě učí!"
- Caveats: Počet se liší od TOTAL_TRADES (pouze trades, které byly ohodnoceny)
- Implementation notes: Čtení z LM canonical state, ne stálé metrics

### LEARNING_HEALTH
- Název v aplikaci: **Zdraví učení (%)**
- Krátký popis: Composited health score LM (0-100%)
- Proč je důležitá: Vidět, zda má bot dostatek dat a kvalitu
- Typ: DERIVED
- Zdroj pravdy: `learning_monitor.py` - lm_health()
- Firebase collection/doc/field: `learning_state/health_pct`
- Log pattern: `[LM_HEALTH]`, `health:`, `score:`
- Formula: Custom weighted formula z LM health components
- Unit: percent
- Data type: float
- Update frequency: Po LM update
- Recommended UI: Progress bar "78% zdravé"
- Priority: **P1**
- Freshness rule: Do 60s
- Green threshold: > 70%
- Yellow threshold: 40-70%
- Red threshold: < 40%
- Czech tooltip: "Jak zdravé je učení robota. <40% = málo dat / šum."
- Caveats: Komplexní formula, možné false positives
- Implementation notes: Cachovat z LM health komponenty

---

## H. Paper Training Diagnostika

### PAPER_TRAIN_ENTRY_COUNT
- Název v aplikaci: **Paper obchody (vstupy)**
- Krátký popis: Počet pokusů o otevření paper training obchodu
- Proč je důležitá: Vidět, zda se paper training aktivuje
- Typ: RAW / LOG_ONLY
- Zdroj pravdy: Log pattern PAPER_TRAIN_ENTRY
- Firebase collection/doc/field: N/A (log only)
- Log pattern: `[PAPER_TRAIN_ENTRY]`
- Formula: count(logs containing PAPER_TRAIN_ENTRY)
- Unit: count
- Data type: integer
- Update frequency: Real-time
- Recommended UI: Text "48 pokusů"
- Priority: **P2**
- Freshness rule: Do 60s
- Green threshold: > 20 (v posledních 24h)
- Yellow threshold: 5-20
- Red threshold: 0 (neprobíhá training)
- Czech tooltip: "Kolik pokusů o paper training. 0 = training vypnutý?"
- Caveats: Počítá se pokusy, ne úspěchy
- Implementation notes: Parsovat z journalctl pro agregaci

### PAPER_TRAIN_ECON_ATTRIB
- Název v aplikaci: **Atribuce papíru (ekonomie)**
- Krátký popis: Rozpad proč papír ztrácí penízje
- Proč je důležitá: Vidět, zda je to fee problém, špatný TP/SL, či špatné signály
- Typ: LOG_ONLY / DERIVED
- Zdroj pravdy: Log pattern PAPER_TRAIN_ECON_ATTRIB
- Firebase collection/doc/field: N/A (log only)
- Log pattern: `[PAPER_TRAIN_ECON_ATTRIB]`, `attrib_`, `cost_edge_bypass`, `fee_dominated`
- Formula: Parsování atribučních kategorií z logu
- Unit: count / percent
- Data type: dict (atribuce -> count)
- Update frequency: Na konci okna (10-60 minut)
- Recommended UI: Tabulka nebo pie chart "Fee 40%, Wrong dir 30%, Timeout 30%"
- Priority: **P1** (diagnostika)
- Freshness rule: Do 2 minut
- Green threshold: fee_dominated < 30%
- Yellow threshold: 30-50%
- Red threshold: > 50% (fee problém)
- Czech tooltip: "Proč papír ztrácí. Vysoké fee% = TP moc blízko ceny."
- Caveats: Dostupné pouze v okně s daty; může být šumné s malým vzorkem
- Implementation notes: Parsování z audit skriptu

---

## I. Signalizace a rozhodovací pipeline

### RAW_SIGNALS_COUNT
- Název v aplikaci: **Surové signály (počet)**
- Krátký popis: Počet všech signálů z signal_generator
- Proč je důležitá: Vidět, zda pipeline je aktivní
- Typ: RAW / LOG_ONLY
- Zdroj pravdy: Log pattern SIGNAL_RAW
- Firebase collection/doc/field: N/A (log only)
- Log pattern: `[SIGNAL_RAW]`, `ENTRY_PIPELINE`
- Formula: count(logs with SIGNAL_RAW)
- Unit: count
- Data type: integer
- Update frequency: Real-time
- Recommended UI: Počítadlo "1,247 signálů"
- Priority: **P2**
- Freshness rule: Do 30s
- Green threshold: > 100 (na den)
- Yellow threshold: 10-100
- Red threshold: 0-10 (málo signálů)
- Czech tooltip: "Počet generovaných signálů. 0 = bez dat?"
- Caveats: Počítá se bez ohledu na kvalitu
- Implementation notes: Agregace z logu

### REJECT_RATE
- Název v aplikaci: **Míra zamítnutí (%)**
- Krátký popis: % signálů zamítnutých RDE
- Proč je důležitá: Vidět, jak selektivní je bot
- Typ: DERIVED
- Zdroj pravdy: (rejected / total) * 100
- Firebase collection/doc/field: N/A (derived from logs)
- Log pattern: `REJECT_`, `NEGATIVE_EV`, `SCORE_GATE`
- Formula: count(REJECT) / (count(REJECT) + count(TAKE)) * 100
- Unit: percent
- Data type: float
- Update frequency: Real-time
- Recommended UI: Procenta "94% zamítáno"
- Priority: **P2**
- Freshness rule: Do 60s
- Green threshold: 80-99% (je selektivní)
- Yellow threshold: 60-80%
- Red threshold: < 60% (málo diskriminace)
- Czech tooltip: "Procento signálů, které RDE zamítne. Vysoké % = konzervativní."
- Caveats: Vysoké % není vždy dobré (može být přesekektivní)
- Implementation notes: Parsování event bus logu

---

## J. Riziko a bezpečnost

### RISK_BUDGET
- Název v aplikaci: **Rozpočet rizika (USD)**
- Krátký popis: Zbývající daily risk budget (max exposure)
- Proč je důležitá: Vidět, kolik rizika zbývá, dříve než je bot zastaven
- Typ: DERIVED
- Zdroj pravdy: `risk_engine.py` - risk budget compute
- Firebase collection/doc/field: `risk_metrics/budget_usd`
- Log pattern: `[RISK_BUDGET]`, `budget:`, `remaining:`
- Formula: max_daily_risk - used_risk_today
- Unit: USD
- Data type: float
- Update frequency: Po každé pozici
- Recommended UI: Procenta s výstražou "75% používáno (zbývá $2,500)"
- Priority: **P1**
- Freshness rule: Do 10s
- Green threshold: > 50% zbývá
- Yellow threshold: 20-50%
- Red threshold: < 20% (blízko haltu)
- Czech tooltip: "Zbývající maximální riziko. <20% = automatický halt!"
- Caveats: Vypočten z odhadu max loss, ne skutečného
- Implementation notes: Sledovat z risk_engine state

---

## K. Kvality execution a slippage

### SPREAD_PCT
- Název v aplikaci: **Spred (%)**
- Krátký popis: Průměrný bid-ask spred jako % ceny
- Proč je důležitá: Vidět náklady na vstup/exit
- Typ: RAW / MARKET
- Zdroj pravdy: market_stream.py - orderbook data
- Firebase collection/doc/field: `execution_quality/spread_pct_avg`
- Log pattern: `Spread:`, `bid-ask:`, `liquidity:`
- Formula: (ask_price - bid_price) / mid_price * 100
- Unit: percent
- Data type: float
- Update frequency: Každý tick
- Recommended UI: Text "0.02% spred"
- Priority: **P2**
- Freshness rule: Do 10s
- Green threshold: < 0.05% (dobrá likvidita)
- Yellow threshold: 0.05-0.2%
- Red threshold: > 0.2% (špatná likvidita)
- Czech tooltip: "Bid-ask spred. Vyšší = dražší obchodování."
- Caveats: Liší se per-symbol a čas
- Implementation notes: Čtení z market_stream orderbook

---

## Metadata a UI panely

### LAST_AUDIT_WINDOW
- Název v aplikaci: **Poslední audit (čas)**
- Krátký popis: Čas poslední spuštění kvality auditu
- Proč je důležitá: Vidět freshness diagnostiky
- Typ: RAW
- Zdroj pravdy: `scripts/p11ag_quality_audit.sh` timestamp
- Firebase collection/doc/field: `diagnostics/last_audit_ts`
- Log pattern: `[AUDIT_START]`, `Audit window:`
- Formula: File mtime nebo log timestamp
- Unit: unix timestamp
- Data type: number
- Update frequency: Každých 60 minut
- Recommended UI: Relativní čas "před 45 minutami"
- Priority: **P2**
- Freshness rule: Do 2 hodin
- Green threshold: < 60 min
- Yellow threshold: 60-120 min
- Red threshold: > 120 min
- Czech tooltip: "Čas poslední diagnostiky. >2h = možné stálé data."
- Caveats: Audit sám spotřebovává čtení
- Implementation notes: Cachovat výsledek auditu

---

**Konec katalogu metrik V1.0**
