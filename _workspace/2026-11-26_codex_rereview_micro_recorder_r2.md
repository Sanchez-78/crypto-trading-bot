# Re-review micro-recorderu rev. 2 (2026-11-26)

## Výsledek

- **A — `stop-tick`: CHANGES_REQUIRED**
- **B — `preflight` + `install`: CHANGES_REQUIRED**

Na server jsem se nepřipojil a nic jsem nenasadil. Nezávisle jsem ověřil SHA-256 všech šesti souborů připnutých v zadání; všechny souhlasí. Testy jsem znovu nespouštěl.

## Uzavřené připomínky

- Výstup `liq_sampled` a protokol správně říkají, že `forceOrder` je neúplný vzorek, nikoli úplný seznam likvidací. Binance uvádí nejvýše jednu událost na symbol za 1000 ms a od dubna 2026 popisuje vybranou událost jako největší v intervalu ([oficiální changelog](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log)).
- `flush()` při nízkém volném místě drží ztrátové okno a při obnovení zápisu vytváří `disk_skip`; při startu přidává značku `start`. Odpovídající cílené testy jsou v nové sadě.
- Forenzní kopie logu se vytváří před zastavením a originální log zůstává na místě.
- Obsah release `micro_recorder.py` odpovídá připnutému hashi i kopii ve `scripts/research/`; unit, design, skript a oba testovací soubory také odpovídají pinům.

## A — `stop-tick`: nutná pojistka proti změně stavu

`stop_tick()` vždy spustí `disable --now tick-recorder.service`, i když forenzní část nezjistí původně popsaný stav. Výstup PID a otevřených FD pouze ukládá; nevyžaduje, aby služba byla aktivní a její proces stále držel očekávaný smazaný SQLite inode. `stat` navíc zkouší bez ověření konkrétní cíl fd 3. Pokud se stav od read-only auditu změnil nebo byla služba opravena, příkaz ji přesto vypne.

Před schválením přidejte fail-closed podmínky pro očekávaný proces/stav a ověřte FD podle skutečného symlink cíle; při nesouladu skončit bez `disable`. Ponechání logu a forenzní archivace jsou správné.

## B — `preflight` + `install`: nutné opravy

1. **Cesty/interpreter se dají přesměrovat prostředím.** Skript přijímá `APP_DIR`, `UNIT_DIR`, `DATA_DIR` a `PY` z prostředí. Unit ale spouští pevně `/usr/bin/python3` ze `/opt/cryptomaster-micro` a ukládá pod `/var/lib/cryptomaster-micro`. Například zděděné `DATA_DIR` může způsobit, že health check ověří jiný adresář, zatímco proces zapisuje jinam; jiné proměnné mohou změnit instalační cíl nebo interpreter. V produkčním režimu odmítněte takové přepsání nebo pevné cíle ověřte proti unit souboru. Testovací přesměrování izolujte explicitním testovacím režimem.

2. **Preflight není read-only a jeho zápis je před rollback trapem.** `python -m py_compile "$HERE/micro_recorder.py"` vytváří `__pycache__` vedle release skriptu. Trap se nastavuje až po `preflight()`, takže neúspěšný preflight může zanechat vedlejší soubor. Použijte kontrolu syntaxe bez zápisu bytecode nebo kompilujte v paměti.

3. **Chybí simulace kritických rollback větví.** Devět testů kontroluje čtyři následné health-check chyby, ale neověřuje návrat při selhání `systemd-analyze verify`, při částečně úspěšném `systemctl enable --now` ani při selhání kopírování/chmod/chown, kdy může zůstat dočasný `.micro.*` soubor. Kód má EXIT trap, ale tyto případy je potřeba pokrýt; dočasné soubory musí být uklizeny i při chybě.

Po opravách ověřte nový diff, piny a testy a požádejte o další review. Do té doby nepovažuji schválení A ani B za udělené. Po případném schválení zůstávají `stop-tick`, `preflight`, `install`, `verify` po 10 minutách a po 24 hodinách samostatné fáze; `stop-tick` se automaticky nevrací zpět při neúspěchu instalace.
