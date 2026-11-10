# Futures flow — výsledky (2026-11-10)

> **Errata (2026-11-10, review; původní čísla a předregistrace beze změny):**
> 1. Checksum ověřil integritu ZIPů, ne úplnost řad. Chybí futures 1m 2026-10-28
>    (1 440 min × 7 symbolů, HOLDOUT) a krátké mezery v metrics (TRAIN 2×, TEST 1×).
>    Report 64 („žádný chybějící archiv“) to v souhrnu nezmínil. Mezery se nedoplňují
>    a nevzniká druhý výsledek HOLDOUT.
> 2. NO_EDGE platí pro testované konfigurace a předpoklady (fixní náklad, close-to-close
>    a 1m TPSL, vstup o minutu později). Nedokazuje, že jsou veřejná data vyčerpaná ani že
>    učící filtr nemůže fungovat. 17 rodin není 17 nezávislých důkazů, protože data a
>    principy se překrývají. Formulace „levné veřejné zdroje jsou vyčerpané“ níže je
>    přehnaná.
> 3. Nulový souhrnný gross nevylučuje rozlišitelné podskupiny. Ověřit by je šlo jen na
>    nových datech, ne na spotřebovaném HOLDOUT. Na HOLDOUT mají H2/H4/H6/H7 u TPSL
>    dolní mez gross CI nad nulou (+0,09 až +0,21 bps). Po nákladu je to ekonomicky
>    bezvýznamné a jde o pozorování po pohledu, ne o objev.
> 4. „+0,02 bps hrubě za 915 obchodů“ pochází z paper fill cen (vstup přes ask/bid,
>    výstup na mid), snapshot `docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261109.json`
>    (± je SE průměru). Není to mid-to-mid ani aktuální stav serveru.
> 5. Bod zvratu `WR_BE = (25 + c) / 60` (56,7 % při 9, 66,7 % při 15, 71,7 % při 18 a 75 %
>    při 20 bps) je dvoubodová aproximace. Timeouty a gapy ji porušují.
> Citlivost na náklady: `_workspace/65_cost_and_learning_review.md`.

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
