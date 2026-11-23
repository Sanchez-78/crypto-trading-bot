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

