# Review deploy skriptu sběrače rev. 7 – 2026-11-27

**Verdikt: APPROVE_TO_DEPLOY** pro postup rev. 7.

## Ověřeno

SHA-256 odpovídají promptu:

- deploy skript rev. 7: `a00b12669a9cd3919fb5445c1ff83604d887600057c85f624d46f754eb33b3b6`
- fallback deploy skript rev. 5: `5832d085ba66f52789b9281ab79f73933a6eac34c7c0ef19a2c4223b2803b4f3`
- sběrač: `b09b31b1bf6bc73904a0ec702049f477f07e39ffb1d65369b0d6bcce1847d466`
- unit: `35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8`
- deploy testy: `0b70fced39b630b5ae3438b653d7ee9cca32c5b594d0e99c0a3d5fb7468e5d12`

Fallback deploy skript se od rev. 7 liší pouze hodnotou `SCRIPT_SHA`, která připíná sběrač rev. 5 (`252dd1f7…`).

`data_dir_ok()` přijímá datový adresář bez symlinku, nebo přesný relativní odkaz `private/<basename>`. U odkazu dále ověřuje rodiče bez symlink komponent, `private` jako skutečný rootem vlastněný adresář s režimem 0700 a cílový adresář jako skutečný adresář. Produkční `DATA` je současně pevně svázané s `/var/lib/cryptomaster-micro`; tím nemůže tento tvar odkazu nasměrovat mimo očekávané `/var/lib/private/cryptomaster-micro`. Kontrola se týká pouze ověření cesty; deploy skript do datového adresáře nezapisuje. `APP_DIR` i adresář unity si ponechávají přísnou kontrolu bez symlinků.

Testy pokrývají přijetí očekávaného odkazu, odmítnutí jiného cíle, nesprávných práv, symlinkovaného `private`, symlinkovaného cílového adresáře a rodiče i instalaci se zachovanými daty. Přijetí testovacího režimu s vlastní UID namísto root UID je přiměřené pro testovací `private` adresář. Přeživší mutace `private_may_be_link` je ekvivalentní: GNU `stat` bez `-L` čte metadata samotného symlinku, jehož režim není 0700, takže ho následná podmínka odmítne.

## Provozní postup a doporučení

Nasazení rev. 7 a následný návrat přes fallback rev. 5 jsou konzistentní. Přijímám popsané testování symlinků jako omezený test: běželo pod `nobody`, v dočasném adresáři a se stuby systémových příkazů, takže neovládalo systemd. Testy jsem sám nespouštěl a serverové provedení nezávisle neověřoval.

Aby se neopakovala odstávka před odhalením chyby preflightu, před příštím odinstalováním spusťte read-only kontrolu připravované verze. Ideálně přidejte režim předběžné kontroly upgradu, který ověří piny, cesty, prostředí a očekávané existující cíle, aniž by vyžadoval jejich odstranění. To je provozní zlepšení pro další upgrade, nikoli blokace nynější opravy: rev. 7 opravuje konkrétní selhání, které nyní brání obnově sběru.

Schválení pokrývá pouze nahrání a použití připnutého deploy skriptu rev. 7 podle popsaných kroků a připravený rollback na rev. 5. Neschvaluje změnu sběrače ani zásah do bota. Žádný SSH přístup, deploy, testy ani čtení serverových dat jsem neprováděl.
