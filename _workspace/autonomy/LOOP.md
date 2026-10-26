# Jeden běh autonomní smyčky (spouští cron v sezení Claude)

Uživatel není u konzole. Odpovídat česky. Pravidla:
`docs/remediation/AUTONOMOUS_LEARNING_LOOP_2026-10-26.md` — nic mimo ně neměnit.

SSH: `ssh -i ~/.ssh/hetzner_root -o ConnectTimeout=15 root@78.47.2.198`

1. Načti `_workspace/autonomy/state.json`. Pokud `finished=true`: smaž svůj cron
   job (CronList/CronDelete) a skonči.
2. Server (jen čtení): `tail -2 /opt/cryptomaster_research/verdict.log`,
   `cat /opt/cryptomaster_research/{stage,DECISION_READY} 2>/dev/null`,
   `tail -3 /opt/cryptomaster_research/stage.log 2>/dev/null`,
   `systemctl is-active cryptomaster cryptomaster-research-eval.timer`.
   - Služba nebo časovač neaktivní, nebo `ERROR` ve verdict.log, nebo poslední
     `verdict.log` řádek starší než 14 h → PushNotification s popisem, nic neopravuj, konec.
3. Vyhodnoť pravidla pro aktuální stupeň (S1, pokud soubor `stage` chybí).
   Termíny počítej podle data UTC; termín S2 = `stage_changed_at` ve state.json + 21 dní.
4. Pokud pravidlo vede na přechod:
   - `ssh … '/opt/cryptomaster_research/apply_stage.sh <S2|S3> check'` → musí vypsat `config ok`.
   - `ssh … '/opt/cryptomaster_research/apply_stage.sh <S2|S3>'` (timeout 45 min).
     Exit 0 = nasazeno; 3 = otevřené pozice, zkus příští běh; jiný = rollback proběhl →
     PushNotification, zapiš do state.json `blocked=true`, další přechody už nedělej.
   - Po úspěchu: `systemctl start cryptomaster-research-eval.service` a ověř nový řádek
     (`stage=<nový>`). Zapiš do state.json `stage`, `stage_changed_at`.
   - Zapiš `_workspace/autonomy/<datum>_<stupeň>.md`: řádek verdiktu, použité pravidlo,
     výsledek nasazení. Commitni jen soubory v `_workspace/autonomy/` a pushni.
   - PushNotification: nový stupeň + důvod (1 řádek).
5. Pokud S3 úspěšně nasazen: napiš `_workspace/autonomy/FINAL.md` (průběh, čísla,
   závěr: cíl nedosažen se stávajícími strategiemi, další krok je nový výzkum strategie
   rozhodnutím operátora; žádné tvrzení o ziskovosti), aktualizuj paměť
   `project_docs_state_20261002.md`, commit + push, `finished=true`, notifikace, smaž cron.
6. GOAL_CANDIDATE → notifikace (jen jednou: `goal_notified=true`), nic neměň.
7. Bez přechodu a bez problému: jen jednovětý souhrn, bez notifikace.
8. Obnova cronu: pokud `cron_created` ve state.json je starší než 6 dní, vytvoř nový
   denní cron (`13 19 * * *`, prompt: „Proveď _workspace/autonomy/LOOP.md“), smaž starý,
   ulož nové `cron_id` a `cron_created`.

Nikdy: měnit kód bota, TP/SL, náklady, symboly, REAL příznaky; nasazovat kód;
přechod zpět; více než jeden přechod za běh; `git add` mimo `_workspace/autonomy/`.
