# Nasazení schválených po-C1 oprav: readiness (dashboard) a viditelnost outboxu (bot)

Stav 2026-11-19: **připraveno, NENASAZENO, čeká na review nasazovacího kroku.** Kód obou oprav má
APPROVE (`_workspace/2026-11-18_codex_review_post_c1_remediation.md`, commit `4581329`). Toto
schválení se netýká nasazení. Plánovač rekonciliace se nenasazuje (`ENABLED=False`, není zapojený).

Artefakty (LF, ploché) a piny: `_workspace/deploy_post_c1_20261119/`, `MANIFEST.json`, generátor
`build_artifacts.py`. Ten ověřuje, že každá serverová kopie z 18. 11. má zaznamenaný SHA a artefakt
se od ní liší přesně o schválený diff.

| Soubor | Služba | preimage (server 18. 11.) | nový SHA-256 | diff |
|---|---|---|---|---|
| `src/services/readiness_monitor.py` | dashboard | `854ccfe9…c5d6` | `1f5d9429…8144` | +13 −54 |
| `src/services/dashboard_web.py` | dashboard | `0fdbf5c8…0b62` | `901807c3…f93c` | +15 −11 |
| `src/services/v5_legacy_bridge/outbox.py` | bot | `a3d7d7a4…4413` | `37cb41b8…faaff` | +47 −0 |
| `src/services/v5_legacy_bridge/outbox_flush_worker.py` | bot | `b173ea7c…6e9e` | `d65614e3…02a4` | +35 −0 |

Plné hashe jsou v `MANIFEST.json`. Před nasazením spočítat hashe znovu lokálně i na serveru.

## A. Dashboard: readiness = `paper_only`

Skript `_workspace/deploy_post_c1_20261119/deploy_dashboard_readiness.sh`
(SHA-256 `a64e36799bba26851e8049817ef5380c28fb420c52817b20b6da63250f822628`, LF).

Co dělá:
1. Bere stejný zámek jako nástroj pro bota.
2. Ověří preimage obou živých souborů; při neshodě odmítne nasazení.
3. Načte zdroj jednou do privátního stage, ověří pin a kompilaci.
4. Zálohuje soubory do `/opt/cryptomaster_deploy_backups/dashboard-readiness-<UTC>`.
5. Nainstaluje pinované bajty se stejným vlastníkem a módem a restartuje **jen**
   `cryptomaster-dashboard`.
6. Ověří:
   - `/healthz` vrací 200;
   - `/api/dashboard/readiness` vrací kontrakt `paper_only`;
   - `/api/dashboard/metrics` vrací 200 (s tokenem z `LoadCredential`, předaným přes stdin);
   - v journalu za 120 s není `Traceback`, `METRICS_COLLECTION_ERROR`, `PermissionError` ani
     `READINESS_CHECK_ERROR`;
   - postimage odpovídá pinu.
7. Při jakékoli chybě obnoví oba soubory, ověří hashe a znovu restartuje dashboard. Pokud rollback
   neprojde, zapíše `ALERT`.

Bot tyto moduly neimportuje (`dashboard_web.py` načítá jen `start_flask_dashboard.py`), takže restart
bota není potřeba.

```text
# soubory z _workspace/deploy_post_c1_20261119/dashboard/ nahrát do /tmp/dashboard-readiness/
# a skript do /opt/cryptomaster_research/, ověřit oba SHA, pak:
bash /opt/cryptomaster_research/deploy_dashboard_readiness.sh
```

Očekávaný účinek: zmizí opakované `[METRICS_COLLECTION_ERROR] Permission denied` a readiness už
netvrdí „Insufficient trading history“. Metriky obchodů se nemění.

## B. Bot: viditelnost terminálního backlogu outboxu

Nástroj `deploy_bot_files.sh` byl rozšířen (commit z 2026-11-19, review požadováno):
- allowlist obsahuje `v5_legacy_bridge/outbox.py` a `outbox_flush_worker.py`;
- záloha vytvoří adresář každého souboru (dříve jen `src/services`, takže vnořená cesta by selhala
  ještě před první změnou);
- skript odmítne dva soubory se stejným jménem, protože zdroj se čte „plochý“.

Na server se musí nainstalovat nová verze `deploy_bot_files.sh` (SHA-256
`822568be05e77efc8d7d361f7b8e55df7b5d0b2fe6889c6664bf7715b5ccf242`) a `deploy_env_check.py`
(`57f0e887e86ec7f27fc8a6c2bebd262597c2eb0876e7e52b672937b894fde025`, obsahuje i úpravu pro strop
bucketu). `deploy_pinned.sh` je beze změny (`74a1fec7…`). Starou verzi před instalací zálohovat
(vzor `stage_backups/deploy-tools-20261112T071304Z`).

Doporučení: **jeden restart bota spolu se stropem bucketu**, pokud ten projde svým review
(`docs/codex_prompts/CODEX_REVIEW_EXPLORE_BUCKET_CAP_2026-11-19.md`). Když ne, nasadit jen outbox:

```text
LABEL=outbox-visibility \
FILES="src/services/v5_legacy_bridge/outbox.py src/services/v5_legacy_bridge/outbox_flush_worker.py" \
VARS="" \
DROPIN_NAME=zzzzzzzzzzzz-outbox-visibility.conf \
EXPECTED_SHA256="src/services/v5_legacy_bridge/outbox.py=37cb41b8a825149404133ca98797fde9cff44d95774fb0c3f8761d6988feaaff src/services/v5_legacy_bridge/outbox_flush_worker.py=d65614e33c7b48bb144b56806a1a8d52a13a5ee20579afb6207b984d7dbf02a4" \
bash /opt/cryptomaster_research/deploy_bot_files.sh
```

S prázdným `VARS` skript drop-in nezapisuje. `DROPIN_NAME` je ale povinný a musí se řadit za
všechny existující drop-iny (skript to ověří). Soubory nahrát do `/tmp/outbox-visibility/`.

Po nasazení ověřit:
- v journalu je jedna řádka `[V5_BRIDGE_OUTBOX_TERMINAL] terminal_unsynced=…` (podle forenzní
  analýzy 18. 11. kolem 2,1 tis.);
- není žádný zápis do Firebase navíc a `pending_count` má dosavadní význam;
- `paper_open_positions` a obchodní funnel jsou beze změny.

Nová řádka `APPLIED OK` ve `stage.log` je marker kohorty, i když obchodní logika se nemění.

## Co se nenasazuje

Plánovač rekonciliace, jakýkoli replay outboxu, reset `retry_count`, DELETE a zápis do Firebase.
Ostatní necommitnuté změny v `dashboard_web.py` (226/73 proti HEAD) a `outbox_flush_worker.py`
nejsou v artefaktech: artefakt = serverová kopie + schválený diff.
