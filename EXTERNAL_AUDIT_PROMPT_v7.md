# Externí audit + poradenství — CryptoMaster HF-Quant 5.0 (kolo 7: LZE vůbec dosáhnout cíle?)

**Od:** provozovatel bota
**Předmět:** (a) nezávisle ověřit metodiku, kterou jsme vyloučili dostupné třídy strategií; (b) jako *poradce* ukázat DOSTUPNOU třídu, kterou míjíme — nebo potvrdit, že v tomto setupu edge není
**Datum:** 20. 7. 2026
**Auditovat @ commit:** aktuální `main`

---

## 0. Absolutní mantinel
**REAL trading = NO-GO.** Vše paper. Nesnižuj náklady jako vedlejší efekt, netiskni secrets, ke každému tvrzení `file:line` / data. **Tuhle negativní evidenci sestavil implementátor — zkus ji ROZBÍT**, ale zároveň jsi žádán o poradenský vstup (co jsme minuli).

## 1. Cíl a co bot UMÍ
- **Cíl:** WR > 50 % **a** kladné paper P&L, poctivě (durable edge, ne gaming metriky).
- **Schopnosti bota:** směrové (long/short) paper obchodování **7 spot USDT majors** (BTC/ETH/ADA/BNB/DOT/SOL/XRP). Ne perp, ne více burz, ne alt-data, ne sub-vteřinová mikrostruktura.
- **Nákladová zeď:** ~18 bp taker round-trip na nohu. Kandidát musí věrohodně překonat ~18 bp hrubě NEBO mít ověřenou ≤~3 bp executable cestu.

## 2. Co jsme RIGORÓZNĚ vyloučili (metodika k ověření)
Offline, na reálných Binance datech (3 roky hodinových barů, 7 majorů), cost-wall-first, chronologický OOS:

| Třída | Nástroj | Výsledek |
|---|---|---|
| **DEV_FADE** (1s mean-revert) | shadow dataset + `maker_fill_model.py` | move ~1–2 bp << 18 bp; maker refutace přecenená (audit v6 verdikt C: midpoint≠fill), ale current impl retired |
| **Breakout** | `costwall_screen.py` | pod zdí (0/7 symbolů OOS+) |
| **Time-series momentum** | `costwall_screen.py` + `costwall_multiregime.py` | 180d okno +85 bp vypadalo skvěle → **regime artefakt** (čistý trend); 3y multi-regime + walk-forward: net ~0/půlka záporná, žádný symbol robustní |
| **Mean-reversion (z-score)** | `costwall_screen.py` | pod zdí (0/7) |
| **Cross-sectional momentum** (relative-value, market-neutral) | `xsec_momentum_screen.py` + `xsec_momentum_stresstest.py` | best config OOS +12 bp/PF 1.29 vypadal jako lead → **short noha −55 bp = celý zisk je long beta**; decay 102→68→8 bp; block-bootstrap CI [−272,+225] → statisticky šum |

**Vzor:** dvě zdánlivé hrany (tsmom, xsec) — obě umřely pod skepsí (beta / small-sample). 

## 3. Otázky pro tebe (auditor + poradce)
1. **Metodika:** je cost-wall screen + stress-test (leg dekompozice, sub-period decay, block-bootstrap CI, purged/chronological OOS) korektní způsob, jak vyloučit třídu? Kde je díra? Je 18 bp/noha realistický, nebo bych měl testovat jiný cost režim?
2. **Missed class (poradenství — nejdůležitější):** existuje třída strategie **implementovatelná směrovým spot botem na 7 majorech** (nebo skromnou extenzí), kterou jsme netestovali a která by věrohodně překonala ~18 bp? Např.:
   - cross-sectional s **jiným signálem** (short-term reversal, low-vol, carry-proxy, volatility-scaled)?
   - **regime-gated** směrový (jen v ověřeném trendu/range)?
   - **event/kalendářní** (funding-hour, expirace, on-chain)?
   - kombinace / ensemble, portfolio konstrukce?
   Buď konkrétní: signál, horizont, jak testovat cost-wall-first.
3. **Realita cíle:** je WR>50 % **a** kladné P&L společně vůbec dosažitelný cíl pro tento univerzum/náklad, nebo je WR>50 % v rozporu s kladnou expektancí (momentum má WR<50 %, high-WR má zápornou expektanci)? Má se cíl přeformulovat (např. PF≥1.2 + kladné P&L, WR jako sekundární)?
4. **Verdikt:** **A)** metodika OK + tady je konkrétní netestovaná dostupná třída (popiš) · **B)** metodika OK + v tomto setupu dostupná edge není → archivovat směrové hledání, jinak nutné nové schopnosti · **C)** metodika má chybu (uveď `file:line`), přepočítej.

## 4. Data k předání
`RESEARCH_COSTWALL_FINDINGS.md`, `RESEARCH_PIVOT_CHARTER.md`, `scripts/research/*` (screen + stress-test), `STRATEGY_EDGE_ANALYSIS.md`, `CryptoMaster_EXTERNAL_AUDIT_REPORT_v6.md`, shadow dataset export. Data jsou veřejné Binance klines — reprodukovatelné.

## 5. Mimo rozsah
REAL trading (NO-GO), bezpečnost/infra (hotovo), learning loop (downstream od signálu). Žádáme **strategický/kvantový** vstup: ověřit negativ + najít dostupnou třídu, nebo potvrdit, že tady edge není.
