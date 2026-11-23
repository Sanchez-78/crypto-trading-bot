# Review nasazovacího kroku: strop průzkumného bucketu (2026-11-23)

Odpovídej česky. Úkol je **review**, ne implementace; snaž se krok zamítnout. Report:
`_workspace/2026-11-23_codex_review_bucket_cap_deploy_step.md`, verdikt `APPROVE` /
`CHANGES_REQUIRED` / `REJECT`. Bez SSH, nasazení, commitu a změny runtime dat.

## Co už je schválené (nepřezkoumávat znovu, jen ověřit, že se nezměnilo)

- Kód a artefakt stropu: `_workspace/2026-11-19_codex_rereview_post_c1_deploy_and_bucket_cap.md`, část C
  = APPROVE. Artefakt `_workspace/bucket_cap_20261119/artifact/paper_trade_executor.py`
  SHA-256 `a39d4f4c3c0d72e3a59a80078be6887ef9f413513b99f5e37d87359e9f406a12`, preimage serveru
  `5b0b15cc0ba98632f866267dac462286c07ecce6d8bbaa9a033120b29fa361cc` (manifest
  `_workspace/bucket_cap_20261119/MANIFEST.json`). Agent 2026-11-23 06:55 UTC ověřil: živý soubor na
  serveru má stále `5b0b15cc…`.
- Nasazovací skript s B4 (kontrola živého preimage): `_workspace/2026-11-19_codex_rereview_outbox_deploy_b4.md`
  = APPROVE; na serveru je `deploy_bot_files.sh` `aa73c519…` a `deploy_env_check.py` `8ae175da…df75`.
  Tento verdikt výslovně **nezahrnoval** vrácení executoru do allowlistu.

## K review

1. `deploy/research_eval/deploy_bot_files.sh` — aplikovaná odložená část
   `_workspace/bucket_cap_20261119/allowlist_executor_after_approval.patch` (jen allowlist + komentář).
   Přesný diff proti HEAD: `_workspace/bucket_cap_deploy_20261123/deploy_bot_files.diff`.
   Nové SHA-256 `64206444a23df72ee1927713773e9ab9b903492424f1748a3843aab7cf960f94` (LF).
2. `tests/test_deploy_bot_files_allowlist.py` — executor v očekávaném seznamu, klíč v allowlistu,
   `EXECUTOR_EXCEPTION` nastaven (patch se na test nedal aplikovat, protože test mezitím dostal testy B4;
   upraveno ručně). Lokálně `test_deploy_bot_files_allowlist.py` + `test_explore_bucket_cap.py`: 40 passed.
3. Plánovaný příkaz (nainstalovat skript `64206444…` se zálohou starého `aa73c519…` do
   `stage_backups/deploy-tools-<UTC>`, artefakt nahrát do `/tmp/explore-bucket-cap/paper_trade_executor.py`):

```text
LABEL=explore-bucket-cap \
FILES="src/services/paper_trade_executor.py" \
VARS="PAPER_EXPLORE_MAX_OPEN_PER_BUCKET=7" \
DROPIN_NAME=zzzzzzzzzzzzz-explore-bucket-cap.conf \
EXPECTED_SHA256="src/services/paper_trade_executor.py=a39d4f4c3c0d72e3a59a80078be6887ef9f413513b99f5e37d87359e9f406a12" \
EXPECTED_PREIMAGE_SHA256="src/services/paper_trade_executor.py=5b0b15cc0ba98632f866267dac462286c07ecce6d8bbaa9a033120b29fa361cc" \
bash /opt/cryptomaster_research/deploy_bot_files.sh
```

   Ověřeno 2026-11-23: poslední drop-in je `zzzzzzzzzzzz-candle-refresh.conf` (nový se řadí za něj);
   klíč není v `/opt/cryptomaster/.env` ani v systemd Environment.

## Zkontroluj zejména

- Že diff skriptu mění jen allowlist (a komentář) a nic z toku B4/rollbacku.
- Že `deploy_env_check.py` na serveru (`8ae175da…`) validuje `PAPER_EXPLORE_MAX_OPEN_PER_BUCKET`
  (1–3 číslice, 1–7) v pre i post kontrole.
- Že staged import celého executoru v sandboxu je bezpečný (side effects importu, Firebase, síť).
- Restart: skript čeká na 0 otevřených pozic — při stropu 2 a ~10 vstupech/h to může trvat; je chování
  při timeoutu bezpečné (bez zápisu)?
- Post-deploy kontroly a rollback (runbook `docs/remediation/POST_C1_DEPLOY_RUNBOOK_2026-11-19.md` část C):
  marker kohorty `explore-bucket-cap`, nesloučit s `candle-refresh`; snížení 7 → 2 pozice nezavírá.
