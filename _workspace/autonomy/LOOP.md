# Jeden běh session smyčky (od 2026-11-09, po externím auditu)

Autorita: `docs/OPERATING_STATE.md`. Tato smyčka **nic nerozhoduje ani nenasazuje**:
měření a protokol běží na serveru. Úkolem je zápis, kontrola zdraví a upozornění.
Odpovídat česky. SSH (jen čtení): `ssh -i ~/.ssh/hetzner_root -o ConnectTimeout=15 root@78.47.2.198`

1. Server: `cat /opt/cryptomaster_research/STATUS; tail -3 /opt/cryptomaster_research/ALERT 2>/dev/null;
   tail -6 /opt/cryptomaster_research/verdict.log; systemctl is-active cryptomaster cryptomaster-research-eval.timer`
   a obchody za 24 h:
   `python3 -c "import sqlite3,time;c=sqlite3.connect('file:/opt/cryptomaster/local_learning_storage/cache.sqlite?mode=ro',uri=True);print(c.execute('select count(*),group_concat(distinct symbol) from closed_trades where entry_ts>?',(time.time()-86400,)).fetchone())"`.
   - `STATUS` není `OK`, nový řádek v `ALERT`, služba/timer neaktivní, poslední běh starší
     než 14 h, nebo < 20 obchodů/24 h → PushNotification + zjistit příčinu čtením. Opravu
     výzkumné části smíš udělat s testy; změnu bota jen podle `OPERATING_STATE.md`.
   Také `systemctl is-active cryptomaster-research-funnel` (neaktivní → stejné upozornění).
2. Zapiš řádek do `_workspace/autonomy/daily.md`: run ID, obchody/24 h, `COHORT_BLIND`
   počty, `FUNNEL` (kandidáti P0.8+ a hlavní kódy odmítnutí), `REPLAY` stav C1 (`fresh_n/final_n`, `days`). Během slepé fáze nečti ani
   nepočítej žádné výsledky (P/L, korelace) čerstvých obchodů po cutoffu — jen počty.
   Uváděj n a CI; `*_NOT_SHOWN` popisuj jako „neprokázáno“, nikdy jako „neexistuje“.
3. C1: dokud `prereg=PENDING`, nic neinterpretuj. Až bude jiný verdikt, zapiš ho a pošli
   notifikaci; další krok jen podle dodatku 1 předregistrace (replikační fáze po review,
   trvalá změna jen s operátorem).
4. Commitni jen `_workspace/autonomy/` a pushni.
5. Obnova cronu: pokud od `cron_created` v `state.json` uplynulo 5+ dní, vytvoř nový denní
   cron (`13 19 * * *`, prompt „Proveď _workspace/autonomy/LOOP.md“), smaž starý, ulož
   `cron_id`, `cron_created`. (Cron v sezení je jen pomocník; měření na něm nezávisí.)

Nikdy: REAL příznaky, TP/SL, náklady, zastavení sběru kvůli virtuální ztrátě, nová
hypotéza bez nové předregistrace, interpretace C1 před pevným koncem.
