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

`stage.log` `DEPLOY_econ-bad-log-limit APPLIED OK` je marker kohorty (změna observability, ne
strategie; obchody před ním a po něm neslučovat).

### Měření (opraveno po re-review D6: žádná pevná cesta v `/tmp`)

Po ≥15 minutách spustit na serveru jako root totéž měření jako ve výchozím stavu (10min okno,
`-o cat`). Všechny dočasné soubory vznikají přes `mktemp` a souhrny se vyhodnotí přímo z nich:

```sh
set -u
T=$(mktemp) && S=$(mktemp) || exit 1
trap 'rm -f "$T" "$S"' EXIT
journalctl -u cryptomaster --since -10min --until -0min --no-pager -o cat > "$T"; rc=$?
[ "$rc" -eq 0 ] && [ -s "$T" ] || { echo "journalctl rc=$rc or empty output: NOT_VERIFIED"; exit 1; }
echo "measured_at=$(date -u +%FT%TZ) window=10min"
echo "main_pid=$(systemctl show cryptomaster -p MainPID --value) active=$(systemctl is-active cryptomaster)"
echo "journal_first_entry=$(journalctl -u cryptomaster --no-pager -o short-iso | head -1 | cut -c1-25)"
echo "all_lines=$(wc -l < "$T") all_bytes=$(wc -c < "$T")"
echo "trace_lines=$(grep -c "\[ECON_BAD_ENTRY_RETURN_TRACE\]" "$T") trace_bytes=$(grep "\[ECON_BAD_ENTRY_RETURN_TRACE\]" "$T" | wc -c)"
echo "decision_print_lines=$(grep -cE "^ +decision=REJECT_ECON_BAD_ENTRY" "$T") decision_print_bytes=$(grep -E "^ +decision=REJECT_ECON_BAD_ENTRY" "$T" | wc -c)"
grep "\[ECON_BAD_REJECT_LOG_SUMMARY\]" "$T" > "$S" || true
echo "summary_lines=$(wc -l < "$S")"; echo "first_summary=$(head -1 "$S")"; echo "last_summary=$(tail -1 "$S")"
echo "paper_entry=$(grep -c "PAPER_ENTRY\]" "$T") p08_open=$(grep -c P0_8_PLUS_LIVE_OPEN "$T")"
journalctl --disk-usage
```

Výstup (ne surový journal) uložit do `_workspace/` jako výsledek měření.

### Kritéria (znění převzaté z re-review D4/D5, nálezy D6–D8)

1. `APPLIED OK`; služba je active, `MainPID` souhlasí s markerem nasazení a po dobu měření se
   nemění. Běžící prostředí má `TRADING_MODE=paper_train`, oba REAL příznaky `false`
   (`ENABLE_REAL_ORDERS`, `LIVE_TRADING_CONFIRMED`) a příznak limiteru
   `RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED=true`. Prokazatelně dostupná část journalu od restartu
   neobsahuje traceback; nedostupný čas je `NOT_VERIFIED` (journal drží jen ~15 min).
2. Pro dva souhrny A/B **ze stejného procesu** ověř `B.seq > A.seq`, `B.since_s > A.since_s`,
   `B.total_rejects ≥ A.total_rejects` a `B.total_suppressed ≥ A.total_suppressed`. Spočti
   `N = Δtotal_rejects`, `S = Δtotal_suppressed`, `R = N / (Δsince_s / 60)`; ověř `0 ≤ S ≤ N` a
   `N − S ≤ 17 × Δseq`. Tato interní kontrola platí i při ztracených souhrnech. Má-li měření méně než
   dva souhrny nebo `N = 0`, je provozní účinek `NOT_VERIFIED`; zjisti, zda bot stále generuje
   odmítnutí.
3. Za desetiminutové okno při stabilních hodinách nepřekročí každý detailní marker
   `17 × počet skutečně zasažených oken` (nejvýše 187). Zaznamenej jeho počet, počet souhrnů, řádky
   a bajty celého journalu. Výchozích 17 444 detailů na marker a 1 744,4 odmítnutí za minutu slouží
   jako kontext, ne jako pevný práh pro tržně proměnlivý provoz.
4. Mezery v `seq` eviduj jako ztrátu observability. Při > 10 % chybějících hodnot mezi A a B prověř
   journald. Samotná mezera nespouští rollback. Při restartu procesu (změna `MainPID`, `seq`/`since_s`
   začnou znovu) se výsledky neslučují a post-check je `NOT_VERIFIED` až do vyšetření restartu.
5. `PAPER_ENTRY` a `P0_8_PLUS_LIVE_OPEN` vypiš jako provozní kontext, ne jako důkaz stejného
   rozhodování ani jako samostatnou podmínku úspěchu (výchozí vzorek má jen 3 a 4 události).
   Neměnnost rozhodování dokládá připnutý schválený diff a jeho testy. Změřenou retenci uveď
   odděleně od odhadu.

Pokud se `NOT_VERIFIED` nezmění ani po opakovaném měření, prověř zdroj odmítnutí a zdraví služby.
Nasazení se neprohlašuje za úspěšné jen na základě nízkého počtu detailů.

## Rollback

- **Bez změny kódu:** odstranit drop-in `zzzzzzzzzzzzzz-econ-bad-log-limit.conf`, `daemon-reload` a
  restart. Příznak bude vypnutý a výstup jako dřív.
- **Úplný:** obnovit `realtime_decision_engine.py` (`4a46037b…`) ze zálohy skriptu.
- Restart s otevřenými pozicemi: pozice jsou persistované, exit lifecycle běží dál.

## Výsledek nasazení (2026-11-23)

**NASAZENO 11:54:37 UTC** (`DEPLOY_econ-bad-log-limit APPLIED OK`, pid 3840326, záloha
`/opt/cryptomaster_deploy_backups/econ-bad-log-limit-20261123T115315Z`). Restart proběhl se 2 otevřenými
PAPER pozicemi na výslovný pokyn operátora, přes `ALLOW_OPEN_POSITIONS=1` (nástroj `3bb51c5e…`,
commit `ff10f96`, dodatečné review požádáno). Po startu `loaded=2 … alive=2`.

Post-check (12:11 UTC, výše uvedený skript, výstup
`_workspace/econ_bad_deploy_20261123/postcheck_journal_20261123.txt`): kritéria 1–5 **PASS**.
- **Sazba odmítnutí:** 1 710/min (výchozí 1 744/min).
- **Detailní výpisy:** 20 + 20 za 10 min (výchozí 17 444 + 17 444).
- **`seq`:** 8–17 souvisle.
- **Změřený účinek:** řádky −25,0 %, bajty textu −39,4 %, retence ~15 → ~22,7 min.
