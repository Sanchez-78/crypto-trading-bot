# Revize po nasazení stropu průzkumného bucketu — 2026-11-23

**Verdikt: bezpečnostní stav po nasazení je doložen pouze hlášením operátora; dosažený počet souběžných pozic je NOT_VERIFIED.** Toto je lokální revize kódu a dokumentů, bez SSH, změny serveru, runtime dat nebo obchodních parametrů.

## Nález P1 — bucketový strop 7 může omezovat globální strop 5

- Schválený executor má `_MAX_OPEN = int(os.getenv("PAPER_MAX_OPEN_POSITIONS", "5"))` (`_workspace/bucket_cap_20261119/artifact/paper_trade_executor.py:150`). Lokální `.env:11` obsahuje `PAPER_MAX_OPEN_POSITIONS=5`; **hodnota na serveru v tomto review ověřena nebyla**.
- Nová funkce `_bucket_cap_for()` vrací 7 pouze pro `P0_8_PLUS_EVIDENCE_COLLECTION` (`:1544–1562`). Vstup ale dále kontroluje celkový počet aktivních PAPER pozic proti `_MAX_OPEN` (`:2042–2057`) a opakuje tuto kontrolu pod zámkem těsně před uložením pozice (`:2454–2463`). Dále platí jeden aktivní průzkumný obchod na symbol (`:1606–1630`).
- Pokud je na serveru efektivní `PAPER_MAX_OPEN_POSITIONS=5`, nejvýš pět pozic může být aktivních **celkem napříč buckety**. Průzkumný bucket tedy nedosáhne sedmi; při obsazenosti jiných bucketů může mít ještě méně slotů. Změna 2 → 7 může přesto umožnit růst z 2 až na 5. Není to otevření REAL cesty ani důvod k automatickému rollbacku.
- Moje předchozí review `_workspace/2026-11-23_codex_review_bucket_cap_deploy_step.md` tento vztah dvou stropů přehlédlo. Jeho `APPROVE` ověřovalo nasazovací postup a bezpečnostní hranice, nikoli dosažení sedmi souběžných pozic; tvrzení o účinném stropu 7 z něj vyvozovat nelze.

## Další čtecí kontrola pro Claude na serveru

1. Ověřit efektivní `PAPER_MAX_OPEN_POSITIONS`: pouze tuto hodnotu v systemd `Environment`/`EnvironmentFile`, případně v počátečním prostředí procesu a v `/opt/cryptomaster/.env`; respektovat `start.py:9–14`, kde `load_dotenv()` doplňuje jen chybějící klíče. Nevypisovat celé prostředí ani jiné hodnoty ze `.env`. Ověřit i `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET=7`, PAPER režim a vypnuté REAL příznaky.
2. Z perzistentního `data/paper_open_positions.json` pořizovat pouze čtecí časově označené agregáty. Pro průzkumný bucket použít stejnou identitu jako executor: `training_bucket or explore_bucket` (`paper_trade_executor.py:1531–1539`), a rozlišit počet pozic v bucketu, celkový počet a počty podle symbolu. Jediný snímek nedokazuje maximum za celé období.
3. Ze SQLite `closed_trades` číst přes read-only připojení bez importu `local_persistent_cache.py`. Nová kohorta začíná `entry_ts >= 1795419902` sekund. Ověřit typ a jednotku timestampů a oddělit obchody otevřené před markerem, které se zavřely po něm. Uvést počty otevření/uzavření, unikátní `trade_id`, efektivní bucket, důvody výstupu a net P/L; z intervalů `entry_ts`–`exit_ts` rekonstruovat souběh včetně překryvu ze starší kohorty. Chybějící či neplatné časy označit jako NOT_VERIFIED.
4. Z krátkého dostupného journalu a trvalejších důkazů ověřit `max_open_per_bucket` versus `max_open_exceeded`, `PAPER_ENTRY`, `PAPER_EXIT`, případné chyby, ALERT a zdraví služby. Journal udrží přibližně 15 minut; nepovažovat absenci starých řádků za důkaz absence chyb. Nezvyšovat logování v této kontrole.
5. Po alespoň 30 minutách provozu uvést, zda počet aktivních průzkumných pozic někdy překročil 2 a zda jej zastavil bucketový, globální či symbolový limit. Pokud nejsou dostatečné snímky, verdikt `NOT_VERIFIED`. Po 24 hodinách dodat popisné tempo obchodů, podíl timeoutů, náklady a post-cost net podle nové kohorty; neslučovat s `candle-refresh` ani z toho nevyvozovat kauzální zlepšení učení nebo edge.

**Žádná automatická změna `PAPER_MAX_OPEN_POSITIONS`.** Je to samostatný obchodní parametr mimo schválený diff, s vlivem na všechny buckety. Rozhodnutí vyžaduje vlastní analýzu rizika, test a review.

## Dostupné důkazy a omezení

- `docs/OPERATING_STATE.md:61–75` zaznamenává marker `DEPLOY_explore-bucket-cap APPLIED OK` v 07:45:02 UTC, hash executoru, PAPER režim, REAL vypnuto a zálohu. Jde o převzatý provozní záznam; v této revizi nebyl server znovu čten.
- `AGENTS.md` neuvádí otevřené zadání. Kód ani testy se zde neměnily; nebyl spouštěn pytest. Pracovní strom zůstal ve svém původním dirty stavu s výjimkou tohoto nového reportu.
