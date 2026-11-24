# Review + rozhodnutí: taxonomie exitů v dashboardu/API/aplikaci a práh průzkumu (Codex, 2026-11-24)

Report napiš česky do `_workspace/2026-11-24_codex_review_exit_taxonomy_and_threshold.md`.
Dva verdikty: **A** APPROVE / CHANGES_REQUIRED (nasazení změny dashboardu), **B** rozhodnutí o prahu
průzkumu. Operátor řekl: „pokud máš nějaký dotaz, udělej ho pro Codex, ať rozhodne“, takže B
rozhoduješ ty.

## A. Dashboard a API nezahrnovaly všechny exity; směr obchodu nebyl srozumitelný

### Zjištění (živé API, jen čtení, 2026-11-24 ~13:30 UTC)

- `exit_distribution` = `{tp 17, sl 28, timeout 57, scratch 0, stagnation 0}`. To je 102 z 334
  obchodů epochy.
- Chybělo 232 obchodů:

  | Kód | Počet |
  |---|---:|
  | `HARD_STOP_VOLATILITY` | 85 |
  | `HARD_STOP_STRUCTURAL` | 72 |
  | `DYNAMIC_TARGET_EXIT` | 57 |
  | `TREND_INVALIDATED` | 18 |

- Příčina: `performance_epoch.epoch_metrics()`, `dashboard_read_model._session_aggregate()` a
  záložní cesta v `dashboard_web.py` znaly jen pět starých kódů.
- Operátor nerozuměl, „proč je obchod dobrý, když exit je menší než entry“. Jde o SHORT (SELL):
  např. SOLUSDT SELL, vstup 69,98, výstup 69,735 → WIN. Tabulka ukazovala holé `SELL` a interní kód.

### Změna

Lokální, necommitnutá. Lokální soubory jsou po normalizaci EOL shodné se serverem.

- Nový `src/services/exit_taxonomy.py`: čistě prezentační, bez obchodní logiky.
  - Skupiny: pět starých klíčů (Android čte přesně ty) a k nim `trailing_stop`, `signal_exit`,
    `risk_exit`, `other` a `total`. Součet skupin = `total` = n.
  - Mapování:

    | Skupina | Kódy |
    |---|---|
    | `tp` | TP, DYNAMIC_TARGET_EXIT |
    | `sl` | SL, HARD_STOP_VOLATILITY (= původní stop, `dynamic_trend_exit_v1:200`) |
    | `trailing_stop` | HARD_STOP_STRUCTURAL (posunutý stop), TRAILING_STOP_EXIT |
    | `signal_exit` | TREND_INVALIDATED, REGIME_INVALIDATED, FLOW_REVERSAL_EXIT, EDGE_DECAY_EXIT |
    | `risk_exit` | RISK_LIMIT_EXIT, DATA_INTEGRITY_EXIT |
    | `timeout` | MAX_HOLD_SAFETY_EXIT a vše s „timeout“ |
    | `other` | cokoli jiného |

  - `describe_trade()` přidá ke každému obchodu `direction` (LONG/SHORT), `direction_label`,
    `exit_group`, `exit_label` (česky) a `price_move_pct` (syrový pohyb trhu, ne P/L).
- `performance_epoch.epoch_metrics()`: všechny exity a `exit_distribution_by_reason`.
- `dashboard_read_model.py`:
  - `_session_aggregate()` vrací 4-tici;
  - nové klíče `exit_distribution_by_reason` a `exit_group_labels` jsou v `get_metrics()`, v
    `_degraded_envelope()` (stejná množina klíčů) i v epochové cestě;
  - `_closed_trades_list()` přidává pole obchodu, takže je dostane i `/api/trades/recent`.
- `dashboard_web.py`:
  - záložní cesta používá stejnou taxonomii;
  - koláč exitů ukazuje všechny neprázdné skupiny s počty;
  - tabulka má sloupce „Směr“ (`SHORT ↓` / `LONG ↑` s vysvětlením), „Pohyb ceny“ a
    „Důvod výstupu“ (česky, kód v tooltipu); colspan je 10.
- Testy `tests/test_exit_taxonomy.py` (7):
  - živý mix 334 kódů;
  - starší kódy a neznámé kódy;
  - SHORT s exitem pod vstupem;
  - `epoch_metrics`;
  - payload `get_metrics` a `get_recent_trades`;
  - degraded obálka.
- Výsledky:
  - s `PYTHONUTF8=1`: 325 passed, 9 skipped (sada `test_dashboard*`, `test_*dashboard*`,
    `test_performance_epoch`, `test_android*`), `PROTECTED_SAME`;
  - bez UTF-8 režimu selžou 3 testy v `test_dashboard_read_model.py` (`read_text()` v cp1250 na
    `PŘIPRAVEN`). To je **předexistující** stav: HEAD `dashboard_web.py` cp1250 také nedekóduje.

### Android aplikace

`C:\Projects\CryptoMaster_app`, bez GitHubu, jen lokálně.
- `src/services/botMetricsRepository.js`:
  - `EXIT_GROUP_KEYS` a `normalizeExitDistribution()` znají všechny skupiny a berou `total` ze
    serveru;
  - `normalizeClosedTrade()` přidává `side`, `direction`, `directionLabel`, `priceMovePct`,
    `exitLabel`;
  - `exitDistributionByReason` a `exitGroupLabels`.
- `ExitsScreen.js`: všechny skupiny s českými názvy a navíc tabulka podle kódu.
- `TradesScreen.js`: karta ukazuje „SHORT (zisk při poklesu ceny)“, „Pohyb ceny“ a „Důvod výstupu“
  (+ kód). Obě cesty sdílí normalizaci.
- `paperLearningAdapter.js`: skupiny navíc.
- `scripts/run-metrics-consistency-tests.cjs`: 22 passed. Release APK se staví (výsledek doplním).

**Ověřit (A):**
- Je mapování sémanticky správné? Hlavně `HARD_STOP_VOLATILITY` → `sl` a `DYNAMIC_TARGET_EXIT` →
  `tp`: mění to význam starých klíčů pro Android, ale odpovídá to „původní stop“ / „cíl zisku“.
- Jsou kontrakty (stejná množina klíčů, never-500) zachované?
- Může jít nasazení dashboardu jen souborově (`exit_taxonomy.py`, `performance_epoch.py`,
  `dashboard_read_model.py`, `dashboard_web.py`) s restartem pouze `cryptomaster-dashboard`?
  - `performance_epoch.py` importuje i bot. Změna je jen v agregaci pro dashboard, ale soubor se
    načte až při restartu bota.
  - Bot nerestartovat, nebo to výslovně posoudit.

## B. Rozhodnutí: práh průzkumu (operátor: „proč stále padá WR a P/L… zlepši!“)

Analýza (jen čtení) je v `_workspace/2026-11-24_wr_pl_decline_analysis.md`.

- **Epocha:** n = 334, WR 33,2 %, −7,74 bps/obchod. Předchozí epocha: WR 25,7 %, −8,84.
  - Šestihodinová okna 41,6 / 25,9 / 37,8 / 26,9 % jsou šum. P/L klesá, protože průměr je záporný.
- **Průzkum:** 333 z 334 obchodů je `P0_8_PLUS_EVIDENCE_COLLECTION`. Vstupy jdou až do modelovaného
  net −25 bps; to je záměr operátora, maximum obchodů pro učení.
- **Ztráty:** ztrátové `HARD_STOP_VOLATILITY` mají medián MFE ~5 bps, jde o chybějící edge vstupu.
- **Prediktor** `predicted_net_edge_bps` třídí WR monotónně (pravidlo zvolené na staré epoše,
  kontrola na nové):

  | Práh | Stará: WR | bps | Nová: WR | bps | Podíl obchodů |
  |---|---:|---:|---:|---:|---:|
  | ≥ −25 (dnes) | 25,5 % | −8,85 | 33,0 % | −7,79 | 100 % |
  | ≥ −10 | 29,8 % | −8,35 | 36,7 % | −5,68 | ~40 % |
  | ≥ 0 | 39,3 % | −5,92 | 39,7 % | −4,75 | ~15 % |
  | ≥ 5 | 44,3 % | −4,40 | 45,5 % | −3,89 | ~10 % |

  Žádný práh nedává kladný průměr.

**Rozhodni:**
1. Ponechat −25 bps (maximum učení).
2. Zpřísnit (≥ −10, nebo ≥ 0): méně ztráty a vyšší WR, ale ~60–85 % méně obchodů pro učení.
3. Jiná varianta.

U změny urči, jestli jde o novou předregistrovanou kohortu. Urči také kritéria a dobu hodnocení,
proti čemu se měří, a co se stane s cílem „co nejvíc obchodů pro učení“ v
`docs/OPERATING_STATE.md`. Hranice:
- TP/SL ani náklady se nemění (`feedback_no_questions_autonomy`);
- žádné REAL.

Bez SSH, nasazení a commitu. Testy:
`PYTHONUTF8=1 python -B -m pytest -q -p no:cacheprovider tests/test_exit_taxonomy.py tests/test_dashboard_read_model.py tests/test_performance_epoch.py`
s kontrolou `protected_sha.py` před a po.
