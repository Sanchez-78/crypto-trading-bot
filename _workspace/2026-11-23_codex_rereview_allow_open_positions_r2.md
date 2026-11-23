# Re-review `ALLOW_OPEN_POSITIONS=1` po opravě R2 (2026-11-23)

**Verdikt: CHANGES_REQUIRED pro další použití povolení.** Prázdné a okrajově odsazené `trade_id` se nyní odmítá, vysvětlení `max_hold_s: null` je opravené a test používá skutečný žurnál v dočasném adresáři. Zůstává ale další čitelný stav, který projde validátorem a loaderem, avšak do žurnálu jej nelze zapsat.

## R3 — P1: neplatné číslo v nepovinném poli zablokuje uzavření

`open_positions_count()` používá `json.loads(text)` a kontroluje konečnost pouze vybraných číselných polí (`deploy/research_eval/deploy_env_check.py:176–221`). Pythonův standardní JSON decoder přijímá tokeny `NaN`, `Infinity` a `-Infinity`; přetečení číselného literálu, například `1e999`, může rovněž vytvořit nekonečno. Plně vyplněný záznam odpovídající kladné fixture `_pos("t")`, rozšířený o `"features":{"x":NaN}`, tedy validátorem projde, protože `features.x` nečte. Loader pozici převezme (`src/services/paper_trade_executor.py:1014–1034, 1079–1085`). Při close je celá pozice součástí `closed_trade` (`paper_trade_executor.py:3655–3661`), ale `PaperCloseJournal.prepare()` serializuje *celý* `closed_trade`, `position` i PnL pomocí `json.dumps(..., allow_nan=False)` (`src/services/paper_close_journal.py:96–101`). To vyvolá `ValueError` ještě před zápisem autoritativního close a `_commit_paper_close_result()` přepne paper state do `FAILED` (`paper_trade_executor.py:3407–3423`). Stejná čísla odmítá i běžný `_save_paper_state()` při dalším uložení (`paper_trade_executor.py:781–818`).

Kanonický writer takový soubor sám nevyprodukuje. Kontrola opt-in má ale právě odmítat poškozený, přesto čitelný soubor před restartem; stejně jako u R2 nestačí ověřit jen pole vybraná pro běžný obchod.

**Požadovaná oprava:** před vrácením počtu ověřit, že celý dekódovaný stav lze serializovat se stejnou numerickou přísností jako žurnál, například `json.dumps(data, allow_nan=False)`, a chybu převést na `Refused`. Pouhé `parse_constant` nestačí pro literál `1e999`; otestovat obě cesty. Regresní test má přidat `NaN` a nekonečno do vnořeného, jinak nepovinného pole u jinak úplné pozice a ověřit odmítnutí před povolením restartu. Úplný konečný záznam má dále projít loaderem a `prepare()`.

## Co R2 opravilo

- Klíč mapy a vlastní `trade_id` se musí shodovat a klíč nesmí být prázdný ani mít okrajové bílé znaky (`deploy_env_check.py:193–199`). Původní proti-příklad R2 se tím zavřel. Test pokrývá pět tvarů prázdného/odsazeného ID (`tests/test_deploy_env_check.py:328–333`).
- Opravený popis `max_hold_s: null` odpovídá skutečné P0.8+ cestě: klíč s `None` loader nemigruje (`paper_trade_executor.py:832–843, 1027–1032`); `_effective_paper_hold_s()` jej čte jako `_MAX_AGE_S` přes exploration větev (`:1235–1254`) a `open_paper_position()` ukládá stejnou konfiguraci do `timeout_s` (`:2275, 2308`).
- U tréninkové pozice test nově opravdu zkrátí uložený timeout z 1200 na 300 s a porovná efektivní držení před a po (`tests/test_deploy_env_check.py:286–323`). V normální tréninkové větvi loader i `_effective_paper_hold_s()` používají `min(max_hold_s, timeout_s, _MAX_AGE_S)` (`paper_trade_executor.py:1038–1057, 1235–1245`), takže závěr o nezměněné době držení platí pro tuto větev.
- Křížový test drží soubor pozic i skutečnou SQLite `PaperCloseJournal` v `tmp_path`; žurnál, ukládání stavu a stale rekonciliace jsou při volání loaderu oddělené stuby (`tests/test_deploy_env_check.py:286–324`). Izolace v provedeném běhu obstála: chráněné otisky jsou stejné. Test dokazuje načtení a zápis několika správných fixture záznamů, ne obecnou platnost tvrzení pro každý záznam přijatý validátorem; R3 je právě neotestovaná protipříkladová větev.

## Ověření a rozsah

Povolený příkaz `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`: **99 PASS, 9 SKIP**. Devět bashových testů se na tomto Windows hostiteli přeskočilo kvůli nedostupnému `bash` v `PATH`; autor uvádí 108 PASS ve svém prostředí, které jsem zde nezopakoval. `protected_sha.py` před a po: **PROTECTED_SAME**; snapshot `_workspace/2026-11-23_allow_open_positions_r2_protected_before.json`. R3 je doložen čtením uvedených větví kódu; nepouštěl jsem syntetický restart ani jiný než povolený testovací soubor.

Server, runtime data, obchodní kód a nasazovací nástroj jsem neměnil. Review se netýká samostatného resetu výkonové epochy; jeho serverový výsledek jsem neověřoval.
