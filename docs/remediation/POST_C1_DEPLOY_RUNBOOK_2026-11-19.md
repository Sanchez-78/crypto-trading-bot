# Nasazení schválených po-C1 oprav: readiness (dashboard), viditelnost outboxu (bot), strop bucketu

Stav 2026-11-19 (kolo 2): **připraveno, NENASAZENO, čeká na re-review nasazovacího kroku.**
- Kód readiness a outboxu má APPROVE (`_workspace/2026-11-18_codex_review_post_c1_remediation.md`,
  commit `4581329`). Nasazovací krok vrátilo review `_workspace/2026-11-19_codex_review_post_c1_deploy_step.md`
  (CHANGES_REQUIRED); nálezy jsou opravené níže.
- Strop bucketu má REJECT (`_workspace/2026-11-19_codex_review_explore_bucket_cap.md`); opravy
  čekají na vlastní re-review (oddíl C).
- Plánovač rekonciliace se nenasazuje (`ENABLED=False`, není zapojený).

## Artefakty a piny

`_workspace/deploy_post_c1_20261119/` (ploché, v gitu byte-exaktní díky `-text`). Artefakt = **bajty serveru** +
reviewovaná změna: nezměněné řádky si drží původní konec řádku. Živý `dashboard_web.py` má smíšené
CRLF/LF a executor je převážně CRLF, takže plošné LF by měnilo řádky mimo diff (opraveno v kole 2).
`build_artifacts.py` ověřuje, že:
- serverová kopie z 18. 11. má zaznamenaný SHA;
- artefakt se od ní liší **přesně o řádky z reviewovaného `remediation.diff`**, u workeru navíc o dva
  řádky `backlog_error` schválené ve druhém kole review. Porovnává se obsah změněných řádků, ne jejich
  počet; jiná změna stejné velikosti neprojde.

| Soubor | Služba | preimage (server 18. 11.) | nový SHA-256 |
|---|---|---|---|
| `src/services/readiness_monitor.py` | dashboard | `854ccfe9…c5d6` | `1f5d9429…8144` |
| `src/services/dashboard_web.py` | dashboard | `0fdbf5c8…0b62` | `df8b5041…e02e` |
| `src/services/v5_legacy_bridge/outbox.py` | bot | `a3d7d7a4…4413` | `37cb41b8…faaff` |
| `src/services/v5_legacy_bridge/outbox_flush_worker.py` | bot | `b173ea7c…6e9e` | `d65614e3…02a4` |

Plné hashe jsou v `MANIFEST.json`. Artefakty po review **znovu negenerovat**: v deploy se použijí
přesně commitnuté bajty a skripty preimage na serveru ověří samy.

## A. Dashboard: readiness = `paper_only`

Skript `_workspace/deploy_post_c1_20261119/deploy_dashboard_readiness.sh`
(SHA-256 `65a133a9bb6befe3ec3e28cdf6321b9198edb3e72b3d9e296a3ebf9f15f7aabc`, LF).

Co dělá:
1. Bere stejný zámek jako nástroj pro bota.
2. **Zjistí účinný profil autentizace živým dotazem ještě před změnou:**
   - 200 bez tokenu = veřejný profil (`docs/remediation/DASHBOARD_DEPLOYMENT.md`);
   - 401/503 = chráněný profil. Token čte z `/run/credentials/cryptomaster-dashboard.service/` (tam ho
     systemd předal běžící službě, funguje i pro šifrovaný credstore) a ověří, že funguje. Jinak
     nasazení odmítne bez jakékoli změny.

   Profil ani autentizaci nemění.
3. Ověří preimage, načte zdroj jednou do stage a ověří pin a kompilaci.
4. Zálohuje, nainstaluje se stejným vlastníkem a módem a restartuje **jen** `cryptomaster-dashboard`.
5. Po restartu ověří:
   - `/healthz` vrací 200;
   - profil je stejný (v chráněném režimu bez tokenu stále 401/503);
   - readiness vrací kontrakt `paper_only` a metrics vrací 200;
   - **journal za 120 s je čitelný a neprázdný** (jinak rollback) a neobsahuje `Traceback`,
     `METRICS_COLLECTION_ERROR`, `PermissionError` ani `READINESS_CHECK_ERROR`;
   - postimage odpovídá pinu **i původnímu módu a vlastníkovi**.
6. Rollback obnoví soubory a ověří hash, mód, UID i GID. Při neúplnosti zapíše `ALERT`.

```text
# soubory z _workspace/deploy_post_c1_20261119/dashboard/ do /tmp/dashboard-readiness/,
# skript do /opt/cryptomaster_research/, ověřit SHA, pak:
bash /opt/cryptomaster_research/deploy_dashboard_readiness.sh
```

## B. Bot: viditelnost terminálního backlogu outboxu

`deploy_bot_files.sh` (SHA-256 `8f0e3219f955cb41674ec0bb0ee795089afca116b9324ed63ca17543b2d7449e`):
- allowlist obsahuje oba soubory outboxu;
- **executor a klíč stropu bucketu jsou z allowlistu odebrané**, dokud strop nemá schválené review,
  takže instalace nástroje neschvaluje nasazení executoru;
- záloha vytváří adresář každého souboru;
- skript odmítne duplicitní jména souborů;
- **nečitelný nebo prázdný journal po restartu vede k rollbacku** (dříve `|| true`).

Na server nainstalovat tuto verzi a `deploy_env_check.py` (`8ae175da…df75`, LF); `deploy_pinned.sh`
je beze změny (`74a1fec7…`). Starou verzi před instalací zálohovat (vzor
`stage_backups/deploy-tools-20261112T071304Z`).

```text
LABEL=outbox-visibility \
FILES="src/services/v5_legacy_bridge/outbox.py src/services/v5_legacy_bridge/outbox_flush_worker.py" \
VARS="" \
DROPIN_NAME=zzzzzzzzzzzz-outbox-visibility.conf \
EXPECTED_SHA256="src/services/v5_legacy_bridge/outbox.py=37cb41b8a825149404133ca98797fde9cff44d95774fb0c3f8761d6988feaaff src/services/v5_legacy_bridge/outbox_flush_worker.py=d65614e33c7b48bb144b56806a1a8d52a13a5ee20579afb6207b984d7dbf02a4" \
bash /opt/cryptomaster_research/deploy_bot_files.sh
```

S prázdným `VARS` skript drop-in nezapisuje, ale `DROPIN_NAME` se musí řadit za všechny existující
drop-iny. Skript to ověří a jinak odmítne. Na hostu to ověřené není. Po nasazení zkontrolovat:
- jednu řádku `[V5_BRIDGE_OUTBOX_TERMINAL] terminal_unsynced=…` (podle 18. 11. kolem 2,1 tis.);
- žádný zápis do Firebase navíc;
- `paper_open_positions` a funnel beze změny.

## C. Strop průzkumného bucketu (vlastní re-review)

Opravy po REJECT:
- **Serverová kopie executoru** stažená 2026-11-19 13:34 UTC jen pro čtení. Její SHA `5b0b15cc…61cc`
  odpovídá dříve uvedenému preimage. Najdeš ji v `_workspace/bucket_cap_20261119/server_copy/`
  i se `SERVER_SHA256SUM`.
- **Artefakt** `artifact/paper_trade_executor.py` (`a39d4f4c3c0d72e3a59a80078be6887ef9f413513b99f5e37d87359e9f406a12`):
  bajty serveru (převážně CRLF) + jen změna stropu, nezměněné řádky bajtově identické. **Úplný diff
  proti serveru** `server_to_artifact.diff`: 2 hunky, +25/−2 (`build_artifact.py` odmítne cizí hunk).
  Dřívější pin `7079c2b5…` byly bajty Windows pracovního stromu (celé CRLF), ne server + diff.
- **Parser** hledá přesnou hodnotu `"1"`–`"7"` bez `int()`, takže 5000 číslic nevyhodí `ValueError`.
  `deploy_env_check.py` omezuje délku na 1–3 číslice a vrací `Refused`.
- **Rozsah:** konfigurovatelný strop platí jen pro `P0_8_PLUS_EVIDENCE_COLLECTION`; ostatní buckety
  zůstávají na 2 (test `test_other_buckets_keep_the_fixed_cap_of_two`).
- **Allowlist:** executor a klíč se vrátí až po schválení patchem
  `_workspace/bucket_cap_20261119/allowlist_executor_after_approval.patch`.

Rollback stropu: snížení hodnoty (např. 7 → 2) otevřené pozice **nezavře**. Další vstupy do bucketu
se odmítají, dokud počet neklesne pod strop; exit lifecycle běží dál. Zaznamenat marker kohorty.
Vyšší počet PAPER obchodů sám neprokazuje lepší učení ani edge.

## Co se nenasazuje

Plánovač rekonciliace, replay outboxu, reset `retry_count`, DELETE a zápis do Firebase. Ostatní
necommitnuté změny v pracovním stromu nejsou v artefaktech: artefakt = serverová kopie + reviewovaný diff.
