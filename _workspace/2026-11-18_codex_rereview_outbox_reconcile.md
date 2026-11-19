# Re-review plánovače rekonciliace outboxu — 2026-11-18

**Verdikt: CHANGES_REQUIRED (jen kód; plánovač zůstává vypnutý).** Původní dvě vady z review jsou opravené, ale `doc_state()` stále přijímá dokumenty, které neodpovídají skutečnému kontraktu writeru. Nad takovým dokumentem pak plánuje zápis. Tento audit nic nenasadil ani nezapnul.

## Nález P2 — neplatný dokument může být `open` nebo `closed`

`LegacyPaperOpenEvent.to_dict()` vždy vydává `trade_id`, `symbol`, `side`, `entry_ts`, `entry_price` a `event_type="paper_open"` (`src/services/v5_legacy_bridge/event_models.py:31-49`). V `outbox_reconcile.py:87-89` však větev `open` nekontroluje `symbol` ani `side`. Reprodukce nad současným kódem:

```python
bad_open = {
    "trade_id": "t", "event_type": "paper_open",
    "entry_ts": 1.0, "entry_price": 100.0,
}
assert doc_state(bad_open, "t") == "open"  # nyní
assert plan([Row("paper_close", "t")], {"t": bad_open}, max_writes=1)[0].action == "WRITE_CLOSE"
```

Stejně projde dokument, v němž chybí jen `symbol` nebo jen `side`. Jde o neúplný cloudový dokument; požadovaný fail-closed výsledek je `unknown` / `UNKNOWN`, nikoli povolení přepsání uzavřením.

Větev `closed` (`outbox_reconcile.py:84-86`) testuje u `symbol` a `side` jen pravdivost hodnoty a přijímá libovolný `event_type` kromě `paper_open`. Například `side="OTHER"` nebo `event_type="quota_publish"` s numerickými exit poli vrátí `closed` a `learning_update` dostane `MERGE_LEARNING`. To nejsou dokumenty z `LegacyPaperCloseEvent.to_dict()` (`event_models.py:73-94`). Současný `build_learning_update()` nevkládá `event_type` do merge payloadu (`learning_bridge.py:155-180`), takže tvrzení, že aktuální learning merge mění `event_type`, současná cesta nepotvrzuje. Kód navíc přijímá nulovou či zápornou cenu jako platný entry/exit údaj; skutečné ceny musí být kladné. Tyto varianty jsou reprodukované čistým importem modulu přes `runpy`, bez DB a Firebase.

**Minimální oprava:** pro `open` i `closed` ověřit `symbol` jako neprázdný řetězec, `side` jako platnou hodnotu `BUY`/`SELL`, čas a cenu jako konečná kladná čísla. U `closed` přijímat `event_type="paper_close"`; jiný typ jen tehdy, pokud je doložený skutečný historický tvar výsledku learning merge a je explicitně omezený. Nejasné tvary mají zůstat `unknown`. Doplnit cílené testy pro výše uvedené dokumenty a mutací ověřit, že bez validace selžou.

## Opravy z předchozího review

Všechny čtyři původní neúplné/rozporné/cizí dokumenty z `post_c1_remediation_review_20261118/independent_final.json` nyní dávají `doc_state(..., "t") == "unknown"` a akci `UNKNOWN`. Při `absent` nebo `open` a současném close + learning funguje rozpočet: při `max_writes=0` se odloží oba zápisy, při 1 se naplánuje jen close, při 2 se naplánuje close a `MERGE_LEARNING` s `expect="closed"`, `depends_on="paper_close:t"`. To opravuje původně odložený learning. `ENABLED=False` (`outbox_reconcile.py:37`); `rg` nenašel import či volání plánovače v `src/`, `bot2/` ani `start.py`. Modul obsahuje jen čistý plán, nikoli I/O nebo executor.

`expect` a `depends_on` správně popisují pořadí v plánu, ale samy o sobě nestačí k bezpečnému budoucímu zápisu. Re-read a následné `set()` bez atomické podmínky nechávají závod, při němž se stav dokumentu mezi kontrolou a zápisem změní. Budoucí executor musí použít transakci nebo ekvivalentní precondition, ověřit identitu/payload a úspěch konkrétní závislé akce. To je **blokátor aktivace**, nikoli tvrzení, že nynější vypnutý plánovač zapisuje.

## Ověření a rozsah

- Povolený cílený běh: `rtk python -B -m pytest -q -p no:cacheprovider tests/test_outbox_reconcile_plan.py` → **27 passed**. Nové hranice validace v těchto testech chybějí.
- Nezávislý read-only reproduktor: chybějící `symbol`/`side` → `open` + `WRITE_CLOSE`; neplatná `side`, cizí `event_type` nebo nulová exit cena → `closed` + `MERGE_LEARNING`.
- SHA-256 všech šesti chráněných runtime souborů před testy a po nich: **6/6 shodných**. `local_learning_storage/cache.sqlite` zůstalo na `0f2fbd24c8b4420b6b6f56fccb24b6d83eb9a6862ee2bca0fd42d12459cf0d7e`. Obsahový rozdíl této lokální DB proti stavu před dřívějším incidentem zůstává `NOT_VERIFIED`.
- Server, Firebase a skutečné cloudové dokumenty: **NOT_RUN / NOT_VERIFIED**. Měnil se pouze tento report; žádný commit, deploy ani zásah do runtime dat.
