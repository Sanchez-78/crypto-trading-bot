# Nasazení: omezení výpisů `REJECT_ECON_BAD_ENTRY` (observability, PAPER)

Stav 2026-11-23: **připraveno, NENASAZENO, čeká na review nasazovacího kroku.**
- Kód má APPROVE: `_workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md`.
- Implementace a testy: `_workspace/2026-11-23_claude_econ_bad_journal_volume.md`.

## Artefakt a piny

| | SHA-256 |
|---|---|
| živý `/opt/cryptomaster/src/services/realtime_decision_engine.py` (read-only scp 2026-11-23 09:14 UTC) | `4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae` |
| artefakt `_workspace/econ_bad_deploy_20261123/artifact/realtime_decision_engine.py` | `95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03` |

`build_artifact.py` ověřuje:
- serverová kopie = preimage;
- nezměněné řádky jsou bajtově identické (soubor je celý CRLF);
- změněné řádky = schválený `rde.diff`;
- artefakt = schválený postimage.

Serverová verze je bajtově shodná s lokálním preimage, takže artefakt je přesně reviewovaný soubor.
V gitu je uložený byte-exaktně (`-text`).

## Ověřeno před nasazením (read-only / jen `/tmp`)

- **Zkouška importu** artefaktu na serveru systémovým `/usr/bin/python3 -I -B` (jako validační
  sandbox) v `/tmp`, s pastí na síťová volání:
  - import projde, 0 síťových volání;
  - jedno daemon vlákno `metrics-worker` (proces skončí normálně);
  - jediný vytvořený soubor je `runtime/firebase_cache.sqlite` v pracovním adresáři (v sandboxu
    zapisovatelný `SCRATCH`);
  - příznak je ve výchozím stavu vypnutý.

  Adresář jsem po zkoušce smazal.
- Klíč `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED` zatím není v `.env` ani v drop-inech. Poslední drop-in je
  `zzzzzzzzzzzzz-explore-bucket-cap.conf`.
- **Výchozí měření journalu (09:17 UTC)** podle postupu z reportu:
  - za 10 minut 152 180 řádků a journal pokrývá ~15 minut;
  - 17 357× `[ECON_BAD_ENTRY_RETURN_TRACE]`;
  - na každé zamítnuté vyhodnocení (~26/s) připadá **6 řádků**: trace a `decision=REJECT_ECON_BAD_ENTRY`
    (tyto dva omezí tato změna) a čtyři výpisy každého vyhodnocení signálu (`EV=… p=… rr=…`,
    `coherence[…]`, `SCORE_THRESHOLD: bootstrap active`, `RDE[…]: ev=…`), tato změna je neomezí.
- **Realistický účinek:** zhruba −1/3 řádků, tedy historie journalu ~22 min místo ~15. Na výrazné
  prodloužení by bylo potřeba omezit i čtyři výpisy každého vyhodnocení, což je samostatná změna
  s vlastním review.

## Nástroj

`deploy/research_eval/deploy_bot_files.sh` (SHA-256 `981c88701f1e093cb1cedceb5637db6605971e23436843b44a32494c78397d29`, LF):
- `ALLOWED_FILES` + `src/services/realtime_decision_engine.py`;
- `ALLOWED_KEYS` + `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED`;
- opravený zastaralý komentář v hlavičce (P3 z review stropu).

Ostatní tok (B4 preimage, sandbox, rollback, kontrola prostředí) je beze změny.

`deploy/research_eval/deploy_env_check.py` (SHA-256 `927cc096afa2db380b2337825906ba6868afb6405d6e13ef346262e0bee351c5`, LF):
klíč přidán do `STRICT_BOOL_KEYS`, takže před nasazením i po něm projde jen `true`/`false`.

Na server nainstalovat obě verze se zálohou starých (`64206444…`, `8ae175da…`) do
`stage_backups/deploy-tools-<UTC>`.

## Příkaz

Artefakt nahrát do `/tmp/econ-bad-log-limit/realtime_decision_engine.py`:

```text
LABEL=econ-bad-log-limit \
FILES="src/services/realtime_decision_engine.py" \
VARS="RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true" \
DROPIN_NAME=zzzzzzzzzzzzzz-econ-bad-log-limit.conf \
EXPECTED_SHA256="src/services/realtime_decision_engine.py=95e499e7446dc663d1c9900c98a7f6d33837091646754145d32d8353d8b22c03" \
EXPECTED_PREIMAGE_SHA256="src/services/realtime_decision_engine.py=4a46037bf5d21c039ba374773b055534dd701ae814f26cf6019cb8e07edf11ae" \
bash /opt/cryptomaster_research/deploy_bot_files.sh
```

## Po nasazení

- `stage.log` `DEPLOY_econ-bad-log-limit APPLIED OK` je marker kohorty (změna observability, ne
  strategie; obchody před ním a po něm neslučovat).
- Proces má `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true`, PAPER a REAL vypnuté a 0 tracebacků.
- Po ~15 minutách zopakovat stejné měření. Očekává se:
  - `[ECON_BAD_ENTRY_RETURN_TRACE]` řádově jen jednotky za minutu (první v okně a kategorii);
  - přibližně 1× za minutu `[ECON_BAD_REJECT_LOG_SUMMARY] seq=…` se zvyšujícím se `seq`;
  - `lines_10min` nižší zhruba o třetinu a pokrytí journalu delší.
- Rozhodování se nemění: počty `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` a funnel by měly zůstat ve stejném
  řádu.

## Rollback

- **Bez změny kódu:** odstranit drop-in `zzzzzzzzzzzzzz-econ-bad-log-limit.conf`, `daemon-reload` a
  restart. Příznak bude vypnutý a výstup jako dřív.
- **Úplný:** obnovit `realtime_decision_engine.py` (`4a46037b…`) ze zálohy skriptu.
- Restart s otevřenými pozicemi: pozice jsou persistované, exit lifecycle běží dál.
