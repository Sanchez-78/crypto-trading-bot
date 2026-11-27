# Review sběrače rev. 6 – 2026-11-27

**Verdikt: APPROVE_TO_DEPLOY** pro popsaný upgrade na rev. 6.

## Kontroly

Hashe skriptu sběrače, deploy skriptu, unity a obou testovacích souborů odpovídají pinům v zadání. Hash návrhu rev. 6 je `99ac1bc994c16ff2410257a06891ba5076cf15726260e40d7b44e29c4bd1c191`.

1. **Oddělená spojení:** rev. 6 směruje `depth20` na `/public/stream` a `forceOrder` na `/market/stream`. Každé spojení běží vlastním vláknem s vlastním backoffem; značky `connect`/`disconnect` obsahují jméno spojení. Neočekávaná výjimka ve vlákně spojení ukončí proces kódem 4, takže nevznikne tichý částečný sběr. Hodinový počet zpráv je užitečná diagnostika. Sdílený čítač je pouze orientační a může při souběžném snapshotu ztratit několik přírůstků; neovlivňuje sbíraná data ani obchodní rozhodnutí.
2. **Upgrade a návrat:** pořadí ruční rollback rev. 5 → preflight/install rev. 6 → verify je konzistentní s připnutými fázemi. Data jsou v odděleném StateDirectory a rollback je nemaže. Návrat přes rollback rev. 6 a install rev. 5 je rovněž souvislý. `start` marker po restartu vyznačí konec mezery ve sběru.
3. **Deploy změna:** deploy skript mění pouze `SCRIPT_SHA`; unit a její pin zůstávají stejné.
4. **Smoke test:** krátký test do dočasného adresáře je přiměřený. Podle předloženého záznamu zachytil zprávy obou streamů a nezasáhl produkční službu ani bota. Tuto serverovou událost jsem nezávisle neověřoval.
5. **`liq_sampled` ve verify:** existence souboru nemá být tvrdou podmínkou úspěchu. Stream může být zdravý, ale během krátkého kontrolního okna nepřijde žádná událost. Doporučuji ji vykázat jako varování/informaci a současně ověřit připojení `market`; při neexistujícím souboru po 10 minutách stačí ruční kontrola. Po 24 hodinách lze absenci vyšetřit spolu s hodinovým počtem zpráv. Aktuální plán ruční kontroly je bezpečný a neblokuje nasazení.

## Omezení review

Neprováděl jsem SSH, deploy, testy ani čtení živých dat. Schválení platí pro upgrade popsaný v rev. 6; neověřuje budoucí dostupnost Binance streamů ani jejich dlouhodobou úplnost. Bot a jeho PID zůstávají mimo rozsah této změny.
