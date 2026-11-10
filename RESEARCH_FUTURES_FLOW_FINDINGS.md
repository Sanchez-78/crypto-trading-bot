# Futures flow — výsledky (2026-11-10)

Offline předregistrovaný screen (Codex, `_workspace/64_codex_new_signal_source_screen.md`,
skript `scripts/research/futures_flow_screen.py`) dat z derivátů a toku objednávek na
horizontu bota (vstup na další minutě, 15 min / TP 35 / SL 25). Veřejná data Binance
2024-01 až 2026-10, 7 párů. Data byla rozdělena na TRAIN, TEST a HOLDOUT, HOLDOUT se
vyhodnotil jednou.

| Hypotéza | HOLDOUT hrubý R15 / TPSL (bps) | po 9 bps |
|---|---|---|
| H1 ΔOI × cena | +0,74 / −0,04 | −8,3 / −9,0 |
| H2 taker long/short ratio | +0,27 / +0,51 | −8,7 / −8,5 |
| H3 top trader vs. retail | +0,15 / −0,04 | −8,8 / −9,0 |
| H4 taker buy imbalance (1m) | +0,41 / +0,41 | −8,6 / −8,6 |
| H5 funding × pohyb | −0,23 / +0,05 | −9,2 / −8,9 |
| H6 BTC vede alty | +0,29 / +0,55 | −8,7 / −8,4 |
| H7 logistická kombinace | +0,88 / +0,75 | −8,1 / −8,3 |

Verdikt: **všech 7 NO_EDGE.** Hrubý pohyb je 0–1 bps proti nákladu 9 bps (reálně 15–20).
WR TPSL 29–37 %, bod zvratu je ~57 %. Výsledek odpovídá živému botovi (+0,02 bps hrubě za
915 obchodů). Testy (29) a kontrolu integrity agent nezávisle zopakoval.

## Souhrnné skóre výzkumu

17 rodin bez edge po nákladech: 6 krátkodobých cenových (`RESEARCH_COSTWALL_FINDINGS.md`),
4 dlouhodobé (`RESEARCH_LONGHORIZON_FINDINGS.md`), funding carry (audit v9 NO-GO)
a 6 veřejných informačních sad z futures zde (+ kombinace). Na horizontu minut až hodin
s taker náklady nemá žádná testovaná veřejná informace hrubý pohyb ani zdaleka
srovnatelný s náklady. Neprokazuje to, že edge nikde neexistuje, ale levné veřejné zdroje
jsou vyčerpané. Další krok je rozhodnutí operátora o cíli, nákladech nebo trhu, nikoli
ladění bota.
