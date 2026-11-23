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

  Adresář jsem po zkoušce smazal. Surový záznam (AUTHOR_REPORTED, nezávisle nepotvrzený) je
  v `_workspace/econ_bad_deploy_20261123/server_import_probe_20261123.txt`.
- Klíč `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED` zatím není v `.env` ani v drop-inech. Poslední drop-in je
  `zzzzzzzzzzzzz-explore-bucket-cap.conf`.
- **Výchozí měření** (09:40 UTC, 10min okno, `-o cat`, tedy jen text zpráv; surově v
  `_workspace/econ_bad_deploy_20261123/baseline_journal_20261123.txt`):

  | | řádky | bajty textu |
  |---|---|---|
  | všechny | 153 824 | 19 429 778 |
  | `[ECON_BAD_ENTRY_RETURN_TRACE]` | 17 444 | 6 733 304 |
  | `decision=REJECT_ECON_BAD_ENTRY` (print) | 17 444 | 1 081 999 |

  Journal pokrýval ~15 min (první záznam 09:25:23). journald drží 95,5 MB a má limity
  `RuntimeMaxUse=100M`, `SystemMaxUse=300M` (`/etc/systemd/journald.conf.d/90-size-limit.conf`), takže se
  retence řídí místem, ne počtem řádků.

## Očekávaný účinek (opraveno po review D1)

Odhad „−1/3 řádků, 22 min“ z předchozí verze byl **chybný**: třetina platí jen pro řádky jednoho
zamítnutého vyhodnocení, ne pro celý journal.
- **Řádky jednoho zamítnutého vyhodnocení:** 2 ze 6 (trace a print). Čtyři výpisy každého vyhodnocení
  signálu (`EV=… p=… rr=…`, `coherence[…]`, `SCORE_THRESHOLD: bootstrap active`, `RDE[…]: ev=…`)
  zůstávají.
- **Všechny řádky journalu:** nejvýše **22,7 %** (34 888 / 153 824).
- **Bajty textu zpráv:** nejvýše **40,2 %** (7,82 MB / 19,43 MB), protože trace řádky jsou dlouhé.

Obě čísla jsou horní meze: první detail v každém okně a kategorii zůstane a přibude ~1 souhrnná řádka
za minutu. Skutečné místo v journalu zahrnuje i pevnou režii metadat na záznam, takže úspora místa leží
mezi podílem řádků a podílem bajtů.

**Retence: NOT_VERIFIED.** Kdyby se řídila jen objemem a rychlost byla stabilní, horní meze by byly asi
19,4 min (podle řádků) až 25 min (podle bajtů textu) místo ~15 min. Skutečnou hodnotu ukáže až měření
po nasazení. Úspěch nasazení na žádné z těchto čísel **nevážu**.

Na výrazné prodloužení by bylo potřeba omezit i čtyři výpisy každého vyhodnocení. To je samostatná
změna s vlastním review.

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
- Po ≥15 minutách zopakovat **stejný** měřicí příkaz jako ve výchozím měření (10min okno, `-o cat`).
  Přesný příkaz, kterým vzniklo `baseline_journal_20261123.txt` (spouští se na serveru jako root):

  ```sh
  J="journalctl -u cryptomaster --since -10min --until -0min --no-pager -o cat"; T=$(mktemp); $J > $T
  echo "measured_at=$(date -u +%FT%TZ) window=10min"
  echo "journal_first_entry=$(journalctl -u cryptomaster --no-pager -o short-iso | head -1 | cut -c1-25)"
  echo "all_lines=$(wc -l < $T) all_bytes=$(wc -c < $T)"
  echo "trace_lines=$(grep -c "\[ECON_BAD_ENTRY_RETURN_TRACE\]" $T) trace_bytes=$(grep "\[ECON_BAD_ENTRY_RETURN_TRACE\]" $T | wc -c)"
  echo "decision_print_lines=$(grep -cE "^ +decision=REJECT_ECON_BAD_ENTRY" $T) decision_print_bytes=$(grep -E "^ +decision=REJECT_ECON_BAD_ENTRY" $T | wc -c)"
  echo "summary_lines=$(grep -c "\[ECON_BAD_REJECT_LOG_SUMMARY\]" $T)"
  echo "paper_entry=$(grep -c "PAPER_ENTRY\]" $T) p08_open=$(grep -c P0_8_PLUS_LIVE_OPEN $T)"
  journalctl --disk-usage; grep "\[ECON_BAD_REJECT_LOG_SUMMARY\]" $T > /tmp/econ_summaries.txt; rm -f $T
  ```

  Souhrnné řádky z okna (`/tmp/econ_summaries.txt`) uložit kvůli výpočtu v bodu 3.
- **Kritéria úspěchu nasazení** (opraveno po re-review D2/D3; nezávislá na velikosti úspory):
  1. `APPLIED OK`, proces má příznak `true`, PAPER/REAL vypnuté, 0 tracebacků.
  2. **Detailní výpisy výrazně klesnou** oproti 17 444 (každý marker) při srovnatelné četnosti
     odmítnutí (bod 3). Tvrdá mez je jen ta, kterou kontrakt skutečně garantuje (D5): **nejvýš
     17 × počet 60s oken zasažených měřeným intervalem** na marker (16 kategorií + `other`, včetně
     okrajových částečných oken a posledního otevřeného okna; 10 min zasáhne nejvýš 11 oken, tedy
     ≤ 187). Počet kategorií z doručených souhrnů se jako tvrdé kritérium **nepoužívá**: poslední
     otevřené okno a ztracené souhrny v něm chybí. Pevné číslo typu „desítky“ není kritérium.
  3. **Četnost odmítnutí jako sazba za skutečnou délku úseku** (D4). Ze souhrnů v měřeném výpisu vzít
     první (A) a poslední (B) doručený:
     `rejects_per_min = (B.total_rejects − A.total_rejects) / ((B.since_s − A.since_s) / 60)`.
     Rozdíl kumulativních součtů je správný i při mezeře v `seq` (ztracené okno je v součtech
     obsažené). Pokrývá jen okna mezi A a B, proto se srovnává **sazba**, ne absolutní počet: výchozí
     sazba je 17 444 / 10 = 1 744,4 odmítnutí za minutu (jedna trace řádka = jedno odmítnutí). Má vyjít
     ve stejném řádu. Součet `window_rejects` lze použít jen při souvislém `seq` mezi A a B. Při méně
     než dvou doručených souhrnech je sazba `NOT_VERIFIED`; měření se zopakuje.
  4. **`seq` roste.** Mezera v `seq` znamená ztracenou souhrnnou řádku (logger/journald), ne chybu
     omezovače ani obchodní regresi. Počty ztracené řádky jsou obsažené v kumulativních součtech
     další doručené řádky. Mezery se zapíšou jako ztráta observability. Samostatný limit pro
     reakci: pokud chybí víc než 10 % `seq` v úseku, prověřit journald (rate limit, místo), ne
     omezovač. Nasazení se kvůli mezerám samým nevrací.
  5. Rozhodování beze změny: `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` ve stejném řádu jako ve výchozím
     měření.
- Skutečnou úsporu řádků a bajtů a novou retenci zapsat jako změřený výsledek, ne jako splnění
  odhadu.

## Rollback

- **Bez změny kódu:** odstranit drop-in `zzzzzzzzzzzzzz-econ-bad-log-limit.conf`, `daemon-reload` a
  restart. Příznak bude vypnutý a výstup jako dřív.
- **Úplný:** obnovit `realtime_decision_engine.py` (`4a46037b…`) ze zálohy skriptu.
- Restart s otevřenými pozicemi: pozice jsou persistované, exit lifecycle běží dál.
