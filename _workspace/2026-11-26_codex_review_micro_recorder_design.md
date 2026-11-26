# Review návrhu micro-recorderu (2026-11-26)

## Verdikt: CHANGES_REQUIRED — zatím neschvaluji nasazení

Nezávisle jsem ověřil SHA-256 návrhu, skriptu, testů a systemd unitu; všechny odpovídají pinům v zadání. Review je lokální a read-only: neprovedl jsem SSH, nenasadil změny a testy jsem znovu nespouštěl.

### Nálezy

1. **`forceOrder` není proud všech likvidací.** Skript ukládá každou přijatou zprávu jako samostatný řádek, ale upstream neposílá každou likvidaci: USDⓈ-M dokumentace uvádí, že stream publikuje nejvýše jednu událost za 1000 ms a aktualizace z dubna 2026 popisuje tuto událost jako největší v daném intervalu. Viz [oficiální changelog Binance](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log), položky 2021-04-27 a 2026-04-10. Protokol a popis dat proto nesmějí slibovat „všechny likvidace“. Buď přejmenujte/zdokumentujte výstup jako vzorkovaný největší liquidation order podle omezení feedu a přijměte, že jde o neúplný proxy signál, nebo navrhněte jiný zdroj. Samotné ukládání každé přijaté zprávy ztrátu upstreamem neřeší.

2. **Při nízkém místě se ztráta dat neoznačí v datasetu.** `flush()` vyjme řádky z bufferů, zjistí volné místo pod 5 GiB, zvýší pouze `skipped_disk` a vrátí se. Čítač se nikde nezapíše do `gaps`; pokud se místo obnoví nebo proces restartuje, pozdější výzkum nemusí poznat, že připojený feed v daném čase nebyl uložen. Test `test_low_disk_skips_writes_and_logs_rate_limited` ověřuje pouze log a čítač, ne značku mezery. Zachovejte informaci o začátku/konec ztráty a počtu vynechaných řádků a přidejte test, že je mezera zapsána po obnovení místa. Selhání zápisu a restart musí zanechat dohledatelný výpadek; pokud to nejde garantovat v datových souborech, musí protokol určit jiný zdroj gap evidence.

3. **Vypnutí starého `tick-recorder` je odůvodněné; smazání logu neschvaluji jako součást tohoto návrhu.** Zastavení procesu by podle uvedených read-only důkazů uvolnilo otevřený smazaný inode a ukončilo chyby. Log v `/tmp` je však jediná detailní provozní stopa uvedených šesti milionů chyb. Ponechte jej nebo nejprve archivujte nezbytný forenzní záznam a jeho hash; odstranění udělejte až jako samostatný, přesně cílený krok po potvrzení cesty a velikosti. Zastavení staré služby lze přezkoumat jako oddělený provozní krok, nikoli sloučit s instalací nového sběrače.

### Co je v pořádku / další postup

- Izolovaný `DynamicUser`, `ProtectSystem=strict`, oddělený `StateDirectory`, limit 128 MiB, `CPUQuota=20%`, idle I/O, rate-limited journald a omezené retry jsou rozumné ochranné vrstvy. Kód podle pinů nenačítá ani neimportuje runtime bota.
- `depth20@500ms` poskytuje částečné snapshoty top 20 úrovní; pojmenování a popis musí zachovat, že nejde o úplnou rekonstruovanou knihu. Jednořádkový sekundový vzorek je přiměřený nízkoobjemový výzkumný formát.
- **`aggTrade` nyní nepřidávat.** Nejdřív opravit úplnost a gap evidenci, ověřit 10min/24h provoz a změřit skutečný přírůstek CPU, paměti a disku. Agregovaný podepsaný objem může být pozdější samostatná revize.
- Nové nasazení má mít samostatný přesně připnutý instalační/rollback postup a validaci hashů na cíli. Provozní kroky staré služby, instalaci sběrače a následnou kontrolu držet jako oddělené, ověřitelné fáze. Po opravách požádat o re-review; teprve potom lze uvažovat o `APPROVE_TO_DEPLOY`.

Nasazení by bylo pouze pro sběr výzkumných dat. Žádný výsledek z něj sám o sobě nebude důkazem signálu ani kladného P/L.
