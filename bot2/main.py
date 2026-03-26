import threading, time

from src.services.market_stream import start
from src.services.firebase_client import init_firebase, daily_budget_report, load_history
from src.services.learning_event import get_metrics, bootstrap_from_history
from src.services.trade_executor import get_open_positions
from src.services.signal_generator import warmup

import src.services.signal_generator
import src.services.trade_executor

_start_time = time.time()
SYMBOLS     = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
W           = 60   # output width


# ── ANSI palette ──────────────────────────────────────────────────────────────

class C:
    GRN = "\033[92m"   # bright green
    RED = "\033[91m"   # bright red
    YLW = "\033[93m"   # yellow
    CYN = "\033[96m"   # bright cyan
    BLU = "\033[94m"   # blue
    MGT = "\033[95m"   # magenta
    WHT = "\033[97m"   # bright white
    GRY = "\033[90m"   # dark grey
    BLD = "\033[1m"    # bold
    DIM = "\033[2m"    # dim
    RST = "\033[0m"    # reset


def g(text, color):
    return f"{color}{text}{C.RST}"


# ── Bars ──────────────────────────────────────────────────────────────────────

def cbar(val, total=1.0, w=16, lo=0.45, hi=0.60):
    """Color-coded progress bar: red / yellow / green."""
    r = min(max(val / total if total else 0, 0.0), 1.0)
    f = int(w * r)
    col = C.GRN if r >= hi else (C.YLW if r >= lo else C.RED)
    return col + "█" * f + C.GRY + "░" * (w - f) + C.RST


def blue_bar(val, total, w=20):
    """Blue progress bar (calibration / confidence)."""
    r = min(max(val / total if total else 0, 0.0), 1.0)
    f = int(w * r)
    col = C.CYN if r >= 0.8 else C.BLU
    return col + "█" * f + C.GRY + "░" * (w - f) + C.RST


def pnl_bar(profit, scale=0.001, w=12):
    """Profit bar centered: green right / red left."""
    r = min(abs(profit) / scale, 1.0)
    f = int(w * r)
    col = C.GRN if profit >= 0 else C.RED
    sign = "▶" if profit >= 0 else "◀"
    return col + sign + "█" * f + "░" * (w - f) + C.RST


# ── Helpers ───────────────────────────────────────────────────────────────────

def sep(char="─"):
    return g(char * (W - 4), C.GRY)


def section(icon, title):
    line = f"  {icon}  {g(title, C.BLD + C.WHT)}"
    return f"\n{line}\n  {sep()}"


def price_arrow(curr, prev):
    if curr > prev * 1.0001: return g("▲", C.GRN)
    if curr < prev * 0.9999: return g("▼", C.RED)
    return g("─", C.GRY)


def uptime():
    s = int(time.time() - _start_time)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


def since_fmt(secs):
    if secs is None or secs <= 0: return "–"
    if secs < 60:   return f"{int(secs)}s"
    if secs < 3600: return f"{int(secs/60)}m {int(secs%60)}s"
    return f"{int(secs/3600)}h {int((secs%3600)/60)}m"


def regime_label(regimes):
    total = sum(regimes.values())
    if not total: return g("čekám na data", C.GRY)
    dominant = max(regimes, key=regimes.get)
    pct = regimes[dominant] / total * 100
    info = {
        "BULL_TREND":  (C.GRN, "📈 BULL TREND  silný vzestup"),
        "BEAR_TREND":  (C.RED, "📉 BEAR TREND  silný pokles"),
        "RANGING":     (C.YLW, "↔️  RANGING     boční pohyb"),
        "QUIET_RANGE": (C.GRY, "😴 QUIET        bez pohybu"),
        "HIGH_VOL":    (C.MGT, "⚡ VOLATILNÍ   velké výkyvy"),
        "TREND":       (C.GRN, "📈 TREND"),
        "CHOP":        (C.YLW, "↔️  CHOP        boční"),
    }
    col, label = info.get(dominant, (C.WHT, dominant))
    return g(f"{label}  ({pct:.0f}%)", col)


# ── Main print ────────────────────────────────────────────────────────────────

def print_status():
    m   = get_metrics()
    lp  = m.get("last_prices", {})
    ls  = m.get("last_signals", {})
    ss  = m.get("sym_stats", {})
    ops = get_open_positions()
    t   = m["trades"]
    wr  = m["winrate"]

    # ── Header ────────────────────────────────────────────────────────────────
    if m["ready"]:
        status_tag = g(" ✅ AKTIVNÍ ", C.BLD + C.GRN)
    else:
        status_tag = g(" 🔄 TRÉNINK ", C.YLW)

    print(f"\n{g('═'*W, C.CYN)}")
    print(g(f"  🤖  CRYPTOMASTER  │  {uptime()}  │{status_tag}", C.BLD + C.CYN))
    print(g("═" * W, C.CYN))

    # ── Live prices ───────────────────────────────────────────────────────────
    print(section("💰", "ŽIVÉ CENY  (Binance · každé 2 s)"))
    for sym in SYMBOLS:
        short = sym.replace("USDT", "")
        if sym not in lp:
            print(f"    {g(short, C.WHT):<4}  {g('čekám...', C.GRY)}")
            continue
        curr, prev = lp[sym]
        arr  = price_arrow(curr, prev)
        pct  = (curr - prev) / prev * 100 if prev else 0
        pcol = C.GRN if pct > 0 else (C.RED if pct < 0 else C.GRY)
        open_tag = g("  ● OPEN", C.YLW + C.BLD) if sym in ops else ""
        print(f"    {g(short, C.WHT + C.BLD):<4}  "
              f"{g(f'${curr:>14,.4f}', C.WHT)}   "
              f"{arr}  {g(f'{pct:+.3f}%', pcol)}"
              f"{open_tag}")

    # ── Open positions ────────────────────────────────────────────────────────
    if ops:
        print(section("🔄", "OTEVŘENÉ POZICE"))
        for sym, pos in ops.items():
            short = sym.replace("USDT", "")
            curr  = lp.get(sym, (pos["entry"], pos["entry"]))[0]
            move  = (curr - pos["entry"]) / pos["entry"]
            if pos["action"] == "SELL": move *= -1
            pnl  = move * pos["size"]
            pcol = C.GRN if pnl >= 0 else C.RED
            act  = g(pos["action"], C.GRN if pos["action"] == "BUY" else C.RED)
            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${pos[\"entry\"]:,.4f}', C.GRY)}→"
                  f"{g(f'${curr:,.4f}', C.WHT)}  "
                  f"{g(f'{pnl:+.6f}', pcol)}  "
                  f"{g(f'TP:{pos[\"tp_move\"]*100:.2f}%  SL:{pos[\"sl_move\"]*100:.2f}%', C.GRY)}")

    # ── Trading performance ───────────────────────────────────────────────────
    print(section("📈", "VÝSLEDKY OBCHODOVÁNÍ"))
    if t == 0:
        print(f"    {g('Žádné uzavřené obchody – zahřívám se...', C.GRY)}")
    else:
        # Win / loss counts
        w_pct = wr * 100
        print(f"    {g('Obchody', C.GRY)}    {g(str(t), C.WHT + C.BLD)}  "
              f"({g(f'✅ {m[\"wins\"]}', C.GRN)}  "
              f"{g(f'❌ {m[\"losses\"]}', C.RED)})")

        wr_col = C.GRN if wr >= 0.55 else (C.YLW if wr >= 0.45 else C.RED)
        print(f"    {g('Winrate', C.GRY)}     "
              f"{g(f'{w_pct:.1f}%', wr_col + C.BLD)}  "
              f"{cbar(wr, 1.0, 18, 0.45, 0.55)}  "
              f"{g('▶ cíl 55%', C.GRY)}")

        pcol = C.GRN if m["profit"] >= 0 else C.RED
        print(f"    {g('Zisk', C.GRY)}        "
              f"{g(f'{m[\"profit\"]:+.8f}', pcol + C.BLD)}  "
              f"{pnl_bar(m['profit'])}")

        ddcol = C.GRN if m["drawdown"] < 0.001 else (C.YLW if m["drawdown"] < 0.005 else C.RED)
        print(f"    {g('Drawdown', C.GRY)}    "
              f"{g(f'{m[\"drawdown\"]:.8f}', ddcol)}  "
              f"{g('(pokles od vrcholu)', C.GRY)}")

        # Streak
        if m["win_streak"] >= 2:
            print(f"    {g('Série', C.GRY)}       "
                  f"{g(f'🔥 {m[\"win_streak\"]}× výhra v řadě!', C.GRN + C.BLD)}")
        elif m["loss_streak"] >= 2:
            print(f"    {g('Série', C.GRY)}       "
                  f"{g(f'💔 {m[\"loss_streak\"]}× prohra v řadě', C.RED)}")

        # Advanced metrics
        pf   = m.get("profit_factor", 1.0)
        exp  = m.get("expectancy",    0.0)
        since = m.get("since_last")
        pf_col = C.GRN if pf >= 1.5 else (C.YLW if pf >= 1.0 else C.RED)

        print(f"    {g('─'*40, C.GRY)}")
        print(f"    {g('Profit Factor', C.GRY)}  "
              f"{g(f'{pf:.2f}×', pf_col + C.BLD)}  "
              f"{g('(zisk ÷ ztráta, cíl > 1.5)', C.GRY)}")
        exp_col = C.GRN if exp > 0 else C.RED
        print(f"    {g('Expectancy', C.GRY)}     "
              f"{g(f'{exp:+.8f}', exp_col)}  "
              f"{g('(průměrný výnos / obchod)', C.GRY)}")
        if m.get("best_trade"):
            print(f"    {g('Nejlepší', C.GRY)}      "
                  f"{g(f'+{m[\"best_trade\"]:.8f}', C.GRN)}  "
                  f"{g('Nejhorší', C.GRY)}  "
                  f"{g(f'{m[\"worst_trade\"]:.8f}', C.RED)}")
        if since is not None:
            print(f"    {g('Poslední obchod', C.GRY)}  "
                  f"{g(since_fmt(since), C.WHT)} {g('zpět', C.GRY)}")

    # ── Per-symbol breakdown ──────────────────────────────────────────────────
    if ss:
        print(section("📊", "VÝSLEDKY PO MĚNÁCH"))
        hdr = (f"    {g('Měna', C.GRY):<5}  "
               f"{g('Obch', C.GRY):>5}  "
               f"{g('WR', C.GRY):>6}  "
               f"{g('Bar (winrate)', C.GRY):<28}  "
               f"{g('Zisk', C.GRY):>12}")
        print(hdr)
        print(f"    {g('─'*52, C.GRY)}")
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            s = ss.get(sym)
            if not s:
                print(f"    {g(short, C.GRY):<5}  {g('–', C.GRY)}")
                continue
            swr   = s["winrate"]
            wcol  = C.GRN if swr >= 0.55 else (C.YLW if swr >= 0.45 else C.RED)
            pcol  = C.GRN if s["profit"] >= 0 else C.RED
            icon  = g("✅", C.GRN) if swr >= 0.55 else (g("⚠️", C.YLW) if swr >= 0.45 else g("❌", C.RED))
            print(f"    {g(short, C.WHT + C.BLD):<5}  "
                  f"{g(str(s['trades']), C.WHT):>5}  "
                  f"{g(f'{swr*100:.0f}%', wcol + C.BLD):>6}  "
                  f"{cbar(swr, 1.0, 16, 0.45, 0.55)}  "
                  f"{g(f'{s[\"profit\"]:+.8f}', pcol):>12}  {icon}")

    # ── Learning ──────────────────────────────────────────────────────────────
    print(section("🧠", "UČENÍ  –  JAK ROBOT ROSTE"))

    cal_pct = min(t / 50, 1.0)
    cal_col = C.GRN if t >= 50 else C.BLU
    print(f"    {g('Kalibrace', C.GRY)}    "
          f"{g(f'{t}/50', cal_col + C.BLD)}  "
          f"{blue_bar(t, 50, 20)}  "
          f"{g(f'{cal_pct*100:.0f}%', cal_col)}")

    rc    = m.get("recent_count", 0)
    rwr   = m.get("recent_winrate", 0.0)
    trend = m.get("learning_trend", "SBÍRÁ DATA...")
    conf  = m["confidence_avg"]

    if t < 10:
        print(f"    {g('Sbírám první data – potřebuji 50 obchodů pro plnou kalibraci.', C.GRY)}")
    else:
        tcol = C.GRN if "ZLEPŠUJE" in trend else (C.RED if "ZHORŠUJE" in trend else C.YLW)
        print(f"    {g('Trend učení', C.GRY)}   {g(trend, tcol + C.BLD)}")
        delta = rwr - wr
        dcol  = C.GRN if delta > 0 else C.RED
        print(f"    {g(f'Posledních {rc}', C.GRY)}   "
              f"{g(f'{rwr*100:.1f}%', C.WHT)}  vs  průměr {g(f'{wr*100:.1f}%', C.WHT)}  "
              f"{g(f'({delta:+.1%})', dcol)}")

    conf_col  = C.GRN if conf >= 0.6 else (C.YLW if conf >= 0.3 else C.RED)
    conf_note = "vysoká ✅" if conf >= 0.6 else ("střední" if conf >= 0.3 else "nízká")
    print(f"    {g('Jistota', C.GRY)}       "
          f"{g(f'{conf*100:.1f}%', conf_col + C.BLD)}  "
          f"{cbar(conf, 1.0, 14, 0.3, 0.6)}  "
          f"{g(conf_note, conf_col)}")

    # ── Strategy / Signals ────────────────────────────────────────────────────
    print(section("⚙️ ", "STRATEGIE  (ADX + EMA + MACD + BB + RSI)"))

    gen = m["signals_generated"]
    exe = m["signals_executed"]
    blk = m["blocked"]
    flt = m["signals_filtered"]
    eff = exe / gen * 100 if gen else 0

    print(f"    {g('Režim trhu', C.GRY)}   {regime_label(m['regimes'])}")
    print(f"    {g('Signály', C.GRY)}       "
          f"{g(str(gen), C.WHT)} zachyceno  "
          f"{g('→', C.GRY)} {g(str(gen-flt), C.WHT)} po filtru  "
          f"{g('→', C.GRY)} {g(str(blk), C.RED)} blokováno  "
          f"{g('→', C.GRY)} {g(str(exe), C.GRN)} provedeno")
    eff_col = C.GRN if eff > 5 else C.YLW
    print(f"    {g('Efektivita', C.GRY)}    "
          f"{g(f'{eff:.1f}%', eff_col)}  "
          f"{g('TP: 2.0×ATR  /  SL: 1.5×ATR  (RR ≈ 1.33:1)', C.GRY)}")

    # ── Last signals ──────────────────────────────────────────────────────────
    if ls:
        print(section("⚡", "POSLEDNÍ ROZHODNUTÍ"))
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            if sym not in ls:
                print(f"    {g(short, C.WHT + C.BLD):<4}  {g('⚪ žádný signál', C.GRY)}")
                continue
            sig  = ls[sym]
            is_buy = sig["action"] == "BUY"
            act  = g("🟢 KUPUJ ", C.GRN + C.BLD) if is_buy else g("🔴 PRODEJ", C.RED + C.BLD)
            res  = sig.get("result")
            rtag = (g("  → ✅ VÝHRA",  C.GRN) if res == "WIN"
                    else g("  → ❌ PROHRA", C.RED) if res == "LOSS" else "")
            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${sig[\"price\"]:,.4f}', C.WHT)}  "
                  f"{g(f'conf:{sig[\"confidence\"]*100:.0f}%', C.GRY)}"
                  f"{rtag}")

    # ── Footer / status ───────────────────────────────────────────────────────
    print(f"\n  {sep('─')}")
    if m["ready"]:
        print(f"  {g('🎯  STAV:', C.BLD)}  {g('✅ AKTIVNÍ  –  robot je kalibrovaný a obchoduje!', C.GRN + C.BLD)}")
    else:
        needs = []
        if t < 50:           needs.append(g(f"obchody {t}/50", C.YLW))
        if wr <= 0.55:       needs.append(g(f"winrate {wr*100:.0f}%→55%", C.YLW))
        if m["profit"] <= 0: needs.append(g("zisk > 0", C.YLW))
        print(f"  {g('🎯  STAV:', C.BLD)}  {g('🔄 TRÉNINK', C.YLW + C.BLD)}  "
              f"{g('(', C.GRY)}{',  '.join(needs)}{g(')', C.GRY)}")
    print(g("═" * W, C.CYN) + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_firebase()
    daily_budget_report()
    bootstrap_from_history(load_history())
    warmup()

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    while True:
        time.sleep(10)
        print_status()


if __name__ == "__main__":
    main()
