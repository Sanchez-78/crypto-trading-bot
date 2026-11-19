# Nezávislé review: plánovač R3 a ochrana v conftestu (2026-11-19)

**A — plánovač: CHANGES_REQUIRED (jen kód).** Reprodukce z minulého review jsou opravené, ale klasifikace stále považuje část neúplných či neplatných cloudových dokumentů za uzavřený obchod.

**B — ochrana testů: CHANGES_REQUIRED.** Změnu obsahu ostatního souboru pod `runtime/` nebo `src/runtime/` lze přehlédnout, pokud se nezmění velikost a `mtime_ns`. Nový soubor a běžný zápis se zachytí. Obě části jsou lokální a plánovač zůstává vypnutý; toto není verdikt k nasazení.

## A — plánovač

`doc_state()` v `src/services/v5_legacy_bridge/outbox_reconcile.py:80-96` teď správně vyžaduje shodu `trade_id`, neprázdný řetězec `symbol`, `side` BUY/SELL, kladné konečné ceny/časy a přesný `event_type`. Původní reprodukce (chybějící symbol/side u open, neplatná side, cizí event_type či nulová exit cena u close) nyní vedou na `unknown` a akci `UNKNOWN`. Skutečný `LegacyPaperOpenEvent.to_dict()` i `LegacyPaperCloseEvent.to_dict()` procházejí; stejně tak close po learning merge. `build_learning_update()` v `learning_bridge.py:157-180` nepřidává `event_type`, včetně jeho rozbaleného `**metadata`: `build_close_metadata()` kopíruje jen vyjmenovaná pole a `event_type` mezi nimi není (`learning_bridge.py:24-40,72-114`). Close proto zůstává `paper_close`.

**Nález A1 (P2): zkrácený close se považuje za úplný.** `LegacyPaperCloseEvent.to_dict()` vždy obsahuje mimo jiné `exit_reason`, `gross_pnl`, `fees`, `spread`, `net_pnl`, `net_pnl_pct`, `duration_seconds`, `learning_eligible`, `real_orders_allowed` a `created_at` (`event_models.py:73-94`). Následující cloudový dokument žádné z těchto polí nemá, přesto je na `outbox_reconcile.py:91-92` klasifikován jako `closed`:

```python
doc = {"trade_id": "t", "symbol": "BTCUSDT", "side": "BUY",
       "event_type": "paper_close", "exit_ts": 2.0, "exit_price": 101.0}
doc_state(doc, "t")  # 'closed'
[a.action for a in plan([Row("paper_close", "t"), Row("learning_update", "t")],
                        {"t": doc}, max_writes=2)]  # ['SKIP_PRESENT', 'MERGE_LEARNING']
```

Tím plánovač přeskočí chybějící close record a dovolí learning merge do neúplného dokumentu. Podobně projde `symbol=" "`, přestože nejde o platný tržní symbol. Zadání výslovně vyžaduje, aby nevalidní dokument nebyl `open` ani `closed`. Doporučuji rozlišit **doloženou úplnost close** od pouhé přítomnosti základních markerů a pro povolení `MERGE_LEARNING` ověřit povinná pole a jejich typy podle skutečného writeru; neznámé/historické tvary ponechat `UNKNOWN`. Pokud je záměr klasifikovat jen podle minimálních markerů, je nutné upravit zadání a zdokumentovat, proč je merge do částečného close bezpečný. K oběma tvarům přidat regresní test, který před opravou selže.

`ENABLED=False` (`outbox_reconcile.py:37`), modul nemá Firebase/DB I/O ani executor a `rg` nenašel volání v `src/`, `bot2/` či `start.py`. Docstring správně uvádí, že budoucí executor potřebuje atomickou transakci nebo precondition; samotné re-read + `set()` nestačí. Stropy 0/1/2 a závislost close → learning dál fungují. Před aktivací navíc musí executor porovnat lokální payload/identitu s cloudovým dokumentem, nejen `trade_id` a typ stavu; plánovač payload v `Row` nemá.

## B — `tests/conftest.py`

Šest jednotlivě vyjmenovaných souborů se při načtení i v `pytest_sessionfinish` porovnává pomocí SHA-256 (`conftest.py:30-46,79-88`). Ostatní soubory pod `runtime/` a `src/runtime/` se registrují podle relativní cesty, velikosti a `mtime_ns` (`conftest.py:47-54`). Sjednocení klíčů zachytí vznik i zmizení souboru. Testy v izolované kopii potvrzují změny dvou chráněných JSON a vznik souboru v obou adresářích; nový guard nezměnil dřívější izolaci importu cache (`conftest.py:60-76`). Povolený běh s `python -B` a `-p no:cacheprovider` prošel.

**Nález B1 (P2): falešně čistý výsledek při stejné velikosti a mtime.** Nad skutečnou funkcí `_protected_snapshot()` extrahovanou z AST souboru jsem použil izolovaný model souboru `runtime/sample.sqlite`: obsah `AAAA` → `BBBB` změnil SHA-256, ale při `st_size=4` a stejném `st_mtime_ns=123` byl snapshot shodný (`content_changed=True`, `guard_detected=False`). Funkce totiž pro tento soubor obsah vůbec nečte. Takový stav lze vytvořit například zápisem a obnovením časového razítka. Jde o skutečnou mezeru proti tvrzení „změna souboru pod runtime shodí běh“. V aktuálním pracovním stromu mají ostatní dvě SQLite DB v těchto adresářích přibližně 20 KiB a 148 KiB, takže kontrola obsahu je zde technicky levná. Doporučuji hashovat obsah i těchto souborů nebo zúžit slib ochrany na změny zjistitelné metadaty; při požadavku na úplnou detekci je nutný hash. Doplnit regresi pro existující soubor se stejnou velikostí a obnoveným mtime a mutaci, která hash znovu nahradí metadaty.

**Falešné poplachy a hranice:** SQLite `-wal`, `-shm` či `-journal` vzniklé nebo zmizelé mezi dvěma snapshoty způsobí selhání, i kdyby je vytvořil jiný proces. Souběžný proces může změnit existující DB a test dostane stejný výsledek; hláška říká pouze „during tests“, neidentifikuje původce. Naopak soubor, který vznikne i zmizí mezi snapshoty, detekován není. `python -B` brání zápisu bytecode aktuálního interpretru, ne všem případným podprocesům. Tyto limity je třeba uvést v dokumentaci; samy o sobě nevyvracejí ochranu koncového stavu. Pro reprodukci souběhu ani krátce žijícího SQLite journalu jsem nespouštěl další procesy: **NOT_VERIFIED dynamicky**.

Stávající mutace conftestu pokrývají jen zúžení na cache, vypnutí skenu adresářů, vypnutí `exitstatus` a vypnutí prevence importu (`mutations_conftest.py`). Chybí mutace vynechání jednoho ze šesti chráněných souborů, ignorování odstranění existujícího souboru a zejména uvedená záměna obsahového hashe za metadata. Současné testy píší do dvou ze šesti chráněných souborů a testují jen vznik souborů pod runtime, nikoli změnu či zmizení již existujícího nevyjmenovaného souboru.

## Ověření a omezení auditu

- Povolené cílené testy: `rtk python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py tests/test_conftest_runtime_db_isolation.py tests/test_outbox_terminal_backlog.py` → **56 PASS** (42 + 8 + 6); AST parse čtyř dotčených Python souborů → **PASS**.
- Původní reprodukce plánovače: všechny `unknown` / `UNKNOWN`; částečný close: `closed` / `SKIP_PRESENT` + `MERGE_LEARNING`. Syntetický metadata probe `conftest._protected_snapshot`: jiný obsah se stejným `st_size`/`st_mtime_ns` neodhalí.
- `protected_sha.py` před testy a po nich: **6/6 SHA shodných** a seznamy souborů pod oběma runtime adresáři shodné. Výchozí hashe jsou již stav po incidentu 19. 11.: `paper_adaptive_learning_state.json=27fd24dc…`, `learning_state_phase1.json=49b740bd…`; nic jsem neobnovoval. Tento helper u dalších souborů pod runtime kontroluje jen *seznam*, ne obsah ani metadata.
- Mutace jsem nespouštěl, protože jejich skripty zapisují výsledky mimo povolený report. V existujícím `mutation_results.json` je **13** mutací plánovače, zatímco Claudeův report uvádí 14/14; počet je třeba opravit nebo doložit chybějící mutaci. Čtyři výsledky conftestu jsem pouze četl, nezávisle je nereprodukoval.
- První pokus o volitelný probe s dočasným souborem skončil oprávněním sandboxu při vytvoření adresáře v systémovém tempu. Poté jsem použil AST-extrahovanou produkční funkci s izolovaným modelem cest bez zápisu souborů. Skutečný server, Firebase a produkční cloudové dokumenty: **NOT_RUN / NOT_VERIFIED**. Žádný commit, deploy ani změna runtime dat.
