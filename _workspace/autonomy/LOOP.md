# Jeden běh autonomní smyčky (od 2026-11-09)

Cíl operátora (2026-11-09): co nejvíce PAPER obchodů pro učení a metriky, proč se
učení zlepšuje/nezlepšuje. Imaginární ztráta nevadí. Stupně S2/S3 zrušeny.
Odpovídat česky. SSH: `ssh -i ~/.ssh/hetzner_root -o ConnectTimeout=15 root@78.47.2.198`

1. Server (jen čtení): `tail -4 /opt/cryptomaster_research/verdict.log`,
   `tail -3 /opt/cryptomaster_research/stage.log`,
   `systemctl is-active cryptomaster cryptomaster-research-eval.timer`,
   počet obchodů za 24 h (na serveru není `sqlite3` CLI):
   `python3 -c "import sqlite3,time;c=sqlite3.connect('file:/opt/cryptomaster/local_learning_storage/cache.sqlite?mode=ro',uri=True);print(c.execute('select count(*),group_concat(distinct symbol) from closed_trades where entry_ts>?',(time.time()-86400,)).fetchone())"`.
   - Služba nebo časovač neaktivní, `ERROR` ve verdict.log, poslední řádek starší než 14 h,
     nebo méně než 20 obchodů za 24 h → PushNotification, zjisti příčinu (jen čtením).
2. Zapiš řádek do `_workspace/autonomy/daily.md`: datum, obchody/24 h, kódy `LEARN`,
   `estimate_rho`, `ctx_p`, `persist_rho`, křivka, verdikt ADAPTIVE−CONTROL.
2b. Z řádku `REPLAY` zapiš verdikt replaye a `prereg=… fresh_n=…`. Sběrný režim:
   `PAPER_LEARNING_CONTROL_FRACTION=1.0` (všichni kandidáti vstupují, odhad se jen loguje).
   - `prereg=CONTRARIAN_CONFIRMED` → podle `docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md`
     implementuj C1 jako `paper_source_learning_v2` za příznakem (testy + mutace), nasaď přes
     `deploy_bot_files.sh` a CONTROL vrať na 0,2. Notifikace.
   - `CONTRARIAN_REFUTED` / `CONTRARIAN_NOT_SHOWN` → beze změny živého pravidla; zapiš do
     daily.md; nová hypotéza jen novou předregistrací (nový dokument + nový `prereg_after`).
   - Replay `HOLDOUT_LIFT_CONFIRMED` na datech po `prereg_after` je kandidát na další
     předregistraci, ne na přímé nasazení.
3. Pokud se v řádku `LEARN` poprvé objeví `CONTEXTS_DIFFER`, `CONTEXTS_PERSIST`,
   `ESTIMATE_RANKS_OUTCOMES`, `CURVE_IMPROVING` nebo `SIGNAL_HAS_GROSS_EDGE` → notifikace (jednou).
4. Commitni jen `_workspace/autonomy/` a pushni.
5. Obnova cronu: pokud od `cron_created` ve state.json uplynulo 5+ dní, vytvoř nový denní cron
   (`13 19 * * *`, prompt „Proveď _workspace/autonomy/LOOP.md“), smaž starý, ulož `cron_id`, `cron_created`.

Nikdy: REAL příznaky, TP/SL, náklady; zastavení obchodování; změny kódu bez testů a
zálohy (vzor `deploy/research_eval/deploy_probe_volume.sh`).
