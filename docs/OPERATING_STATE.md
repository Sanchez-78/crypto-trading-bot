# Aktuální provozní stav — jediný index autority

Aktualizováno: 2026-11-09. Při rozporu má tento soubor přednost před staršími
dokumenty; starší dokumenty jsou historický záznam. Kdo mění stav, aktualizuje tento soubor.

## Cíl (operátor, 2026-11-09)

„Imaginární ztráta nevadí, potřebujeme co nejvíce obchodů pro proces učení a metriky,
proč se učení zlepšuje/nezlepšuje.“ Bot je **PAPER only**. Virtuální ztráta není důvod
k zastavení. Cíl WR > 50 % / kladné P/L z `CLAUDE.md` není aktuální měřítko práce.

**Doplněno operátorem 2026-11-09 ~10:00 UTC:** „pokračuj autonomně, cíl P/L+, WR > 50 a
dokonalý a zlepšující se proces učení.“ Výklad agenta: P/L+ a WR > 50 % jsou konečný cíl,
cestou k němu je proces učení; C1 je test, zda učení vůbec nese signál, takže zmrazení
sběru platí dál (operátor C1 nezrušil). Pozor: při TP 35 / SL 25 bps a nákladech 9 bps
je bod zvratu WR ≈ 56,7 % (výhra +26, ztráta −34 bps), takže WR > 50 % samo P/L+ nezaručí.

## Aktivní konfigurace (server `/opt/cryptomaster`, nasazeno souborově, ne z gitu)

| Položka | Hodnota | Zdroj |
|---|---|---|
| Limity průzkumu | 480/den, 30/h, cooldown 300 s, min. modelovaný net −25 bps | drop-in `zzzzzzzzzz-probe-volume.conf` |
| Symboly | všech 7 (blacklist prázdný) | tamtéž |
| CONTROL podíl | 1,0 (sběr: adaptivní odmítání vypnuto, odhad se loguje) | drop-in `zzzzzzzzzzz-learning-collect.conf` |
| TP/SL, náklady | beze změny (35/25 bps, fee 8 + slippage 1 bps) | `/opt/cryptomaster/.env`, overlay |
| Stupně S2/S3 | **zrušeny**, stage timer a skripty odstraněny | — |

„Všichni kandidáti“ znamená jen bez adaptivního odmítnutí; pacing, risk, kvóty, data a
generátory dál určují, co vstoupí.

## Aktivní experiment

- **C1_contrarian**, předregistrace `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`
  včetně dodatku 1: cutoff `prereg_after=1794209516`; jediné vyhodnocení prvních 1 000
  čerstvých obchodů, nejdřív po 7 UTC dnech (~2026-11-16). Do té doby `PENDING`, výsledky skryté.
- Historický experiment ADAPTIVE vs CONTROL (do 9. 11.): `SELECTION_EFFECT_NOT_SHOWN`,
  uzavřen — při CONTROL = 1 nová ramena nevznikají.

## Měření (server, nezávislé na sezení Claude)

- `cryptomaster-research-eval.timer` 05:47 a 17:47 UTC → `/opt/cryptomaster_research/run_eval.sh`.
- Každý běh: `reports/<UTC run ID>/` s `manifest.json` (SHA snapshotu, kódu, env),
  `report.*` (epocha do cutoffu), `replay.*`; zámek proti souběžným během.
- `verdict.log`: řádky `EPOCH`, `LEARN_EPOCH` (obojí jen do cutoffu C1), `REPLAY`
  (exploratorní jen do cutoffu + stav C1) a `COHORT_BLIND` (jen počty čerstvých obchodů).
  Plný report MAX_DATA kohorty (`cohort/`) až po zmrazeném výsledku C1.
- `STATUS` = poslední výsledek (`OK` / `FAILED:<krok>`); selhání spustí
  `cryptomaster-research-alert.service` → `ALERT` soubor a journal (priorita err).
- `prereg_result.json` (neměnný) vzniká uvnitř běhu při prvním závěrečném verdiktu C1;
  když pak selže zbytek běhu, výsledek už zmrazený je (vyhodnocení proběhlo právě jednou).
  Souběžný běh odmítnutý zámkem skončí tiše (exit 0).
- `cryptomaster-research-funnel.service` (od 9. 11.): čte journal bota a ukládá hodinové
  počty fáze funnelu (kandidáti P0.8+ podle kódu, vstupy, pacing, skipy) do
  `funnel/YYYYMMDD.jsonl`; bez cen a výsledků (bezpečné pro slepou fázi). Řádek `FUNNEL`
  ve `verdict.log` = posledních 12 h. Důvod: journal bota drží jen ~15 min (objem logu).
- **Mezera:** žádný kanál, který by operátora upozornil bez sezení Claude (otázka 4 níže).
- **Ztráta kandidátů od 07:30 UTC 2026-11-09:** `REJECT_STALE_MARKET_DATA` 118× vs. 87
  vstupů za 07:30–10:16 (předchozí 2 dny 0×), od začátku populace C1. Oprava odložena
  po výsledku C1. Detail a fronta: `_workspace/62_stale_market_data_rejections_since_restart.md`.
- **Disk 2026-11-09 (opraveno 10:18 UTC):** růst ~3,6 GiB/den způsobuje `/var/log/syslog`
  (rsyslog kopíruje ~13 000 řádků/min stdout bota; pravidlo `30-cryptomaster-stop.conf`
  je mrtvé, bot loguje jako `python3`), ne `shadow_excursion.sqlite` (~50 MiB/den).
  Zásah: zkomprimován uzavřený `syslog.1` a z `/etc/logrotate.d/rsyslog` odstraněno
  `delaycompress` (záloha `/root/logrotate.d-rsyslog.bak-20261109`) → 88 % → 83 %,
  minimum volného místa před denní rotací ~4 GiB. Syslog bota záměrně NEvypnut: journald
  je jen v RAM, takže `/var/log/syslog*` je jediná trvalá historie logů bota.
  Detail: `_workspace/61_disk_shadow_excursion_growth_risk.md` (errata nahoře).

## Povolené akce agenta

Operátor opakovaně autorizoval autonomní práci („pokračuj autonomně“, „po automatické
analýze nasaď vše potřebné“, „pracuj autonomně“, 26. 10.–9. 11.) a commit/push po každém
commitu. **2026-11-09 ~09:55 UTC operátor potvrdil: „dělej vše bez ptaní“.** Rozsah níže
tím platí bez dalších dotazů; bezpečnostní hranice (sekce „Vyžaduje operátora“, PAPER only)
zůstávají:

- Čtení serveru (SSH read-only), výpočty, reporty, dokumentace, commit a push.
- PAPER změny výzkumné části (`/opt/cryptomaster_research`) s testy.
- PAPER změny bota jen přes `deploy/research_eval/deploy_bot_files.sh` (allowlist,
  zámek, záloha, rollback) a **po nezávislém review přesného diffu**, pokud mění
  rozhodovací politiku, protokol experimentu nebo nasazovací skripty.

**Zmrazení sběru během C1:** dokud není hodnocená množina C1 kompletní (≥ 1 000 čerstvých
obchodů a 7 dní), agent nemění konfiguraci sběru (limity, cooldown, min. net, symboly,
CONTROL podíl, generátory) — změnila by cílovou populaci předregistrace.

## Vyžaduje operátora

Nová hypotéza mimo předregistraci, změna cíle, trvalá změna politiky učení, cokoli
mimo PAPER, změna TP/SL nebo nákladů.

## Nahrazené / historické dokumenty

| Dokument | Stav |
|---|---|
| `docs/remediation/AUTONOMOUS_LEARNING_LOOP_2026-10-26.md` | S1→S2→S3 zrušeno 9. 11. |
| `_workspace/autonomy/2026-11-09_S2.md` | historický; S2 vrácen na S1 o 7 min později |
| `_workspace/58_why_bot_does_not_improve.md` | část závěrů opravena (viz Errata v souboru) |
| `CLAUDE.md` — CORE ARCHITECTURE, autonomní 30min smyčka do WR > 50 % | zastaralé pro současnou PAPER cestu |
| `AGENTS.md` — zákaz commit/deploy | psáno pro Codex/externí agenty; uplatnění na Claude je výklad agenta (čeká na potvrzení) |

## Výchozí odpovědi na otevřené otázky auditu (agent; platí na základě „dělej vše bez ptaní“)

1. Hlavní výsledek: více kvalitně atribuovaných vzorků + měření, zda pořadí učení
   předpovídá výsledek. Net na obchod je sekundární.
2. C1 = jednorázový test s pevným koncem (dodatek 1), celková chybovost 5 %.
3. Po potvrzení jen omezená replikační PAPER fáze po review; trvalou změnu schvaluje operátor.
4. Alert mimo sezení: **neřešeno** — potřeba kanál od operátora (e-mail/Telegram/jiný).
5. Autorita: `manifest.json` každého běhu + `POSTIMAGE.sha256` každého deploye.
6. 9 bps zůstává primární měřítko učení; realistické poplatky (15–20 bps) vykazovat zvlášť.
7. Zdroje: sledovat disk (83 % po opravě rotace syslogu 2026-11-09), RAM a Firebase kvóty při vyšším objemu.
