# Re-review micro-recorderu rev. 3 (2026-11-26)

## Verdikt

- **A — `stop-tick`: CHANGES_REQUIRED**
- **B — `preflight` + `install`: CHANGES_REQUIRED**

Review byl read-only: bez SSH, nasazení a opakování testů. Nezávisle jsem ověřil SHA-256 všech šesti připnutých souborů; všechny souhlasí.

## Potvrzené opravy

- `stop-tick` před vytvořením forenzního adresáře kontroluje aktivní stav, MainPID, `tick_recorder.py` v cmdline a přesný cíl otevřeného FD na smazanou DB.
- Produkční cesty a Python jsou pevné mimo výslovný test režim; preflight ověřuje `ExecStart` a `StateDirectory` a kontrola syntaxe používá `compile()` bez zápisu bytecode.
- `place()` při chybě čistí svůj dočasný soubor. Byly přidány testy selhání `systemd-analyze verify`, částečného `enable --now` a `chown`.
- Opravy vzorkovaných likvidací (`liq_sampled`) a záznamu `disk_skip`/`start` z předchozí revize zůstávají zachované.

## A — stále nutná kontrola těsně před vypnutím

Po počátečním ověření stavu skript počítá hash a komprimuje log, kopíruje jeho začátek i konec a zapisuje forenzní soubory. Teprve potom volá `systemctl disable --now`. Během této potenciálně dlouhé operace se proces může restartovat nebo změnit; skript před vypnutím znovu neověří MainPID, cmdline ani FD. V takovém případě by mohl vypnout novou či opravenou instanci, přestože ji při prvním ověření neviděl.

Před `disable` znovu ověřte, že služba stále běží se stejným PID, cmdline a FD na přesný smazaný inode. Při nesouladu skončete bez vypnutí. Přidejte test změny PID/stavu během forenzní fáze.

## B — rollback a cílové cesty stále nejsou dostatečně omezené

1. **Rollback maže cizí soubory.** Řádek `rm -f "$APP_DIR"/.micro.* "$(dirname "$UNIT_PATH")"/.micro.*` maže všechny odpovídající soubory v cílových adresářích. V `/etc/systemd/system` může být `.micro.*` soubor jiné operace; tento skript jej nezná ani neověřuje jeho hash. To odporuje deklaraci, že rollback odstraní jen své vlastní/připnuté soubory. Sledujte přesné dočasné cesty vytvořené aktuálním během a čistěte jen ty; přidejte test, který prokáže, že cizí `.micro.*` zůstane.

2. **Kontrola cest neodmítá symlink rodičovského adresáře.** Preflight ověřuje nepřítomnost cílového souboru, ale neověřuje, že `/opt/cryptomaster-micro` a rodič `UNIT_PATH` nejsou symlinky ani že jejich kanonické cesty odpovídají schváleným cílům. Symlink v `APP_DIR` může přesměrovat instalaci například do stromu bota, přestože proměnné prostředí nejsou přepsané. Ověřte kanonické cesty a odmítněte symlinkované/nečekané rodiče.

3. **`mv -f` může přepsat soubor vytvořený po preflightu.** Po kontrole neexistence cíle se používá nucené přejmenování. Použijte atomické vytvoření bez přepsání nebo znovu bezpečně ověřte cíl; přidejte případ souběžně vzniklého cizího cíle do testů.

Po těchto opravách požádejte o další review. `stop-tick` i instalace zůstávají samostatné fáze; toto schválení nebylo uděleno a na serveru se nic nemá spouštět.
