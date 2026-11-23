# Re-review `ALLOW_OPEN_POSITIONS=1` po opravě A1 (2026-11-23)

**Verdikt: CHANGES_REQUIRED pro další použití opt-in.** Původní A1 pro neslovníkový záznam je opraven: `{"trade-1": 42}`, skalár, seznam a obalový formát nová kontrola odmítá. Zůstává však případ, kdy přijatý záznam loader po restartu změní v ekonomicky podstatných polích. Opravený nástroj podle zadání dosud není na serveru; server jsem nekontaktoval.

## R1 — P1: validátor přijme pozici, kterou loader nenačte beze změny

`open_positions_count()` vyžaduje jen shodné `trade_id`, neprázdný `symbol` a kladné konečné `entry_price` a `entry_ts` (`deploy/research_eval/deploy_env_check.py:151–187`). Pro následující JSON tedy vrátí `1`:

```json
{"t":{"trade_id":"t","symbol":"BTCUSDT","entry_price":100,"entry_ts":1}}
```

`_load_paper_state()` ale každý přijatý záznam před vložením do `_POSITIONS` normalizuje (`src/services/paper_trade_executor.py:1014–1038`). `_normalize_position_for_loading()` u tohoto příkladu doplní `size_usd=10`, `side=BUY` a výchozí TP/SL (`:861–906`); `_migrate_legacy_position()` doplní `max_hold_s` (`:832–858`). Chybějící `side` má přímý dopad: při uzavření se znovu použije výchozí `BUY` pro PnL (`:3634–3647`). Pokud byl původní záznam SHORT a směr se z něj ztratil, opt-in povolí restart, který jej vyhodnotí jako LONG. Záznam se sice neskryje jako v původním A1, ale tvrzení validátoru „restores 1:1“ a „never ... reshape“ není splněno.

Navíc samotná kladnost `entry_price` a `entry_ts` nedokazuje použitelnost `side`, `size_usd`, `tp`, `sl`, `max_hold_s`, účetních polí ani dalších uložených hodnot. Produkční `open_paper_position()` tato pole do kanonické pozice skutečně zapisuje (`paper_trade_executor.py:2244–2270`). Současná kladná testovací fixture je sama neúplná: `_pos()` v `tests/test_deploy_env_check.py:214–223` neobsahuje velikost, TP/SL ani max hold.

**Požadovaná oprava:** před povolením restartu odmítnout záznamy, kterým loader doplní nebo změní ekonomicky významné hodnoty. Minimálně ověřit platný směr `BUY`/`SELL`, kladnou konečnou velikost, platné TP/SL, `max_hold_s` a další pole používaná při close podle aktuálního kanonického kontraktu. Pokud má platit doslovné „1:1“, ověřit také, že loaderova normalizace a migrace ani tréninková normalizace nemění přijaté záznamy. Test, který bez opravy selže, má pokrýt zejména chybějící `side`, `size_usd`, `tp`, `sl` a `max_hold_s`; běžný úplný stav musí projít. V preflightu neimportovat executor jen kvůli validaci: jeho import má runtime vedlejší efekty. Příliš přísné odmítnutí starého stavu je u opt-in přijatelný fail-closed výsledek.

## Co oprava A1 již řeší

- Větev skriptu se spustí pouze při přesném `ALLOW_OPEN_POSITIONS=1`. Volá izolovaný Python a při nenulovém návratu validátoru skončí `SKIPPED` před rollback trapem i před prvním zápisem do živého kódu (`deploy/research_eval/deploy_bot_files.sh:132–150, 179–191`). Bez opt-in zůstala původní čekací smyčka. Hlavička skriptu už výjimku uvádí.
- Validátor správně odmítá neplatný JSON, neobjektový kořen, nepodporovaný obal nebo seznam, klíč `metadata`, neslovníkovou pozici, odlišné `trade_id` a chybná čtyři kontrolovaná pole (`deploy_env_check.py:160–187`). Chyba čtení souboru končí kódem 2 (`:199–208`). V těchto případech se původní A1 neopakuje.
- Odmítnutí legacy seznamu a obalu je správně konzervativní: loader je sice umí převést, ale opt-in nemusí přijímat formáty vyžadující migraci. Mohou způsobit zbytečné `SKIPPED`, nikoli nebezpečné povolení. Stejně tak starší platné pozice bez interního `trade_id` mohou být odmítnuty; je to přijatelné.
- Ani úplný soubor nelze obecně porovnávat 1:1 jen podle počtu v JSON. Loader před obnovou filtruje ID s již potvrzeným uzavřením v žurnálu (`paper_trade_executor.py:1006–1017`); nižší počet po restartu pak může být správný. Kontrola R1 se týká *změny obsahu neuzavřené pozice*.

## Zbývající provozní meze a dokumentace

`docs/OPERATING_STATE.md:100–107` dokládá, že při minulém konkrétním restartu byly dvě pozice načteny. Neprokazuje obecnou bezpečnost opt-in. Runbook uvádí jen „pozice jsou persistované, exit lifecycle běží dál“ (`docs/remediation/ECON_BAD_LOG_LIMIT_DEPLOY_2026-11-23.md:160–170`). Pro další použití doplnit: close přerušený před potvrzením žurnálu může po restartu nastat později a za jinou cenu; po zahájení ne-idempotentních hooků může obnova zůstat nejistá a vyžadovat ruční zásah (`paper_trade_executor.py:3362–3404`). Rollback také restartuje s otevřenými pozicemi (`deploy_bot_files.sh:151–177`). U budoucích změn executoru nebo formátu stavu musí samostatné review ověřit kompatibilitu *nového i vraceného* kódu se stavem otevřených pozic. Tyto meze jsou mimo přímou opravu A1, ale současná dokumentace je nepopisuje dostatečně.

## Ověření

Povolený příkaz `python -B -m pytest -q -p no:cacheprovider tests/test_deploy_bot_files_allowlist.py tests/test_deploy_env_check.py tests/test_deploy_pinned.py`: **59 PASS, 9 SKIP**. Devět bashových testů se na tomto Windows hostiteli přeskočilo, protože `bash` není v `PATH` (`tests/test_deploy_pinned.py:10–11`). Autor uvádí 68 průchodů v prostředí s bashem, což jsem nezávisle neopakoval. `protected_sha.py` před a po: **PROTECTED_SAME**; snapshot `_workspace/2026-11-23_allow_open_positions_a1_protected_before.json`. Proti-příklad R1 plyne přímo z uvedených větví kódu; živý restart ani import executoru jsem nespouštěl. Žádný serverový, obchodní ani nasazovací soubor jsem neměnil.
