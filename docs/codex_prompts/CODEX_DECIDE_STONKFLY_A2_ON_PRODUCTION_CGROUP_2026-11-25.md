# Rozhodnutí: smí Stonkfly A2 běžet na produkci souběžně v omezeném cgroup? (Codex, 2026-11-25)

Jen audit a rozhodnutí, bez SSH, nasazení a commitu. Report napiš česky do
`_workspace/2026-11-25_codex_decide_stonkfly_a2_production_cgroup.md`.

Verdikt:
- **APPROVE_PRODUCTION_CGROUP** s přesnými podmínkami, nebo
- **REJECT**, kdy zůstává dočasný izolovaný stroj.

## Proč se ptám

Operátor se ptá, proč A2 nejde pustit na stávajícím serveru. Dočasný stroj zatím nevznikl: lokálně
chybí `hcloud` token i WSL.

Tvůj dřívější audit `_workspace/2026-11-24_codex_a2_production_option_review.md` posuzoval jen
**pauzu** živého Stonkfly a ten zamítl (chybí pause/resume, šlo by to jen restartem bota). Tady jde
o jinou variantu: živý bot i živý Stonkfly worker běží dál beze změny a A2 poběží **vedle nich**
v samostatném, tvrdě omezeném systemd scope.

## Fakta ze serveru (jen čtení, 2026-11-25 ~09:58 UTC)

| | Hodnota |
|---|---|
| Disk `/` | 38 GB, volných 15 GB. A2 potřebuje ~0,5 GB (data 260 MB, závislosti 152 MB) + checkpointy |
| RAM | 3819 MiB celkem, `available` 2249 MiB, **swap 0** |
| Živý Stonkfly worker | RSS ~695 MB. Historicky live HWM 925 634 560 B a offline HWM ~902 MiB (`_workspace/52_paired_stonkfly_report_20261013.md:209–211`) |
| Ostatní procesy | bot `start.py` RSS ~226 MB, `tick_recorder` ~115 MB, dashboard ~42 MB |
| CPU | 2 vCPU, **load average ~2,0** (1, 5 i 15 min), takže CPU je už dnes plně vytížené |
| Limity služby | systemd 255, cgroup v2 s řadiči `cpu io memory pids`. `cryptomaster.service` nemá `MemoryMax`, `CPUQuota` ani `Nice` |
| OOM | `journalctl -k` za 30 dní: 0× „out of memory“ |

A2 pouští postupně čerstvý paired worker pro každý snímek (12 snímků × 3 opakování), pak jednu
sekvenci a nakonec statický R8 child. Workery neběží souběžně, takže očekávaná špička je ~1 GB.

## Navrhovaná varianta (zatím neimplementovaná)

```
systemd-run --unit=stonkfly-a2 --wait --collect \
  -p MemoryMax=1300M -p MemorySwapMax=0 -p CPUQuota=50% -p Nice=19 \
  -p IOSchedulingClass=idle -p TasksMax=64 \
  -p ProtectSystem=strict -p ReadWritePaths=/srv/a2 -p PrivateTmp=yes \
  -p ReadOnlyPaths=/opt/cryptomaster -p ReadOnlyPaths=/var/lib/cryptomaster \
  -p NoNewPrivileges=yes -p RuntimeMaxSec=4h \
  --setenv=TRADING_MODE=paper_train ... stonkfly_a2_network_controls.py
```

- **Paměť:** OOM při překročení 1300M zabije jen A2 uvnitř cgroup. Rezerva vůči `available` je
  ~950 MiB pro bot a živý worker.
- **CPU:** A2 dostane nejvýš 50 % jednoho jádra s nice 19. Při plném vytížení tak spíš poběží
  pomalu, než aby ubral živému botu.
- **Data a kód:** kopie v `/srv/a2/{code,data,stonkfly}` mimo `/opt/cryptomaster` a
  `/var/lib/cryptomaster`. Ty jsou v jednotce jen pro čtení. Nepoužije se `.env`, runtime DB ani
  živý checkpoint.
- **Úprava skriptu:** `refuse_production_host()` dnes produkci odmítá. Nově by ji připustil jen
  s explicitním přepínačem `--production-cgroup` a jen tehdy, když `/proc/self/cgroup` ukazuje na
  `stonkfly-a2` a `memory.max` je ≤ 1300M. Jinak odmítne jako dnes. Výsledný JSON zapíše
  `host: production_cgroup` a limity.
- **Omezení výsledku:** měřené časy a RSS by byly zkreslené souběžnou zátěží. Verdikty A2 stojí na
  aktivitě a dekodéru, ne na čase. Ekonomika se nehodnotí.
- **Úklid:** po běhu se smaže `/srv/a2`.

## Ověř a rozhodni

1. Je souběžný běh v tomto cgroup bezpečný pro živý PAPER bot a živý Stonkfly worker? Vezmi
   v úvahu RAM bez swapu, CPU v saturaci, I/O a page cache.
2. Neporušuje to pravidlo „na 4GB produkci nespouštět druhou instanci modelu“? Pokud je pravidlo
   absolutní, napiš **REJECT**.
3. Je limit 1300M správný? Nebo je nejdřív potřeba změřit špičku A2 jinde (např. `--smoke`
   v cgroup)?
4. Jaké změny skriptu a testy vyžaduješ (guard `--production-cgroup`, kontrola cgroup, záznam
   hostu)? Mění se tím schválený protokol A2 (`_workspace/2026-11-24_codex_rereview_stonkfly_a2_r1_r3.md`)?
5. Jaké jsou podmínky přerušení během běhu (např. `available` < X MiB, chyba bota v journalu,
   změna PID bota nebo živého workeru)?
