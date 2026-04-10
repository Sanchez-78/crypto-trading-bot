import threading, time

from src.services.market_stream import start
from src.services.firebase_client import init_firebase, daily_budget_report, load_history, save_metrics_full
from src.services.learning_event import get_metrics, bootstrap_from_history
from src.services.trade_executor import get_open_positions
from src.services.signal_generator import warmup
from src.services.dashboard_live import dashboard_loop
from bot2.auditor import run_audit

import src.services.signal_generator
import src.services.trade_executor

_last_audit      = 0
_last_metrics    = 0
_last_pre_audit  = 0
AUDIT_INTERVAL      = 30      # seconds — bot2 auditor cycle
METRICS_INTERVAL    = 30      # save metrics/latest every 30 s
PRE_AUDIT_INTERVAL  = 7200    # pre_live_audit replay run every 2 hours

_start_time = time.time()
from src.services.portfolio_discovery import get_active_symbols
W           = 60


# ── ANSI palette ──────────────────────────────────────────────────────────────

class C:
    GRN = "\033[92m"
    RED = "\033[91m"
    YLW = "\033[93m"
    CYN = "\033[96m"
    BLU = "\033[94m"
    MGT = "\033[95m"
    WHT = "\033[97m"
    GRY = "\033[90m"
    BLD = "\033[1m"
    DIM = "\033[2m"
    RST = "\033[0m"


def g(text, color):
    return f"{color}{text}{C.RST}"


# ── Bars ──────────────────────────────────────────────────────────────────────
#
#  Thin-line style (inspired by modern UI):
#    filled  ━  U+2501  thick horizontal
#    empty   ─  U+2500  thin horizontal
#    bubble  ●  shown at the fill point with % label
#
BAR_W = 22   # all bars same width


def cbar(val, total=1.0, w=BAR_W, lo=0.45, hi=0.60):
    """
    Thin progress bar with floating % bubble at the tip.

        ━━━━━━━━━━━━●─────────  45%
    """
    r   = min(max(val / total if total else 0, 0.0), 1.0)
    f   = max(int(w * r) - 1, 0)
    col = C.GRN if r >= hi else (C.YLW if r >= lo else C.RED)
    pct = f"{r*100:.0f}%"
    filled = col + "\u2501" * f
    tip    = col + "\u25cf"          # ●
    empty  = C.GRY + "\u2500" * (w - f - 1)
    label  = " " + g(pct, col + C.BLD)
    return filled + tip + empty + label + C.RST


def blue_bar(val, total, w=BAR_W):
    """
    Blue stepped bar for calibration — caps at 100%.

        ━━━━━━━━━━━━●─────────  46%
    """
    r   = min(max(val / total if total else 0, 0.0), 1.0)
    f   = max(int(w * r) - 1, 0)
    col = C.CYN if r >= 1.0 else C.BLU
    pct = "100%" if r >= 1.0 else f"{r*100:.0f}%"
    filled = col + "\u2501" * f
    tip    = col + "\u25cf"
    empty  = C.GRY + "\u2500" * (w - f - 1)
    label  = " " + g(pct, col + C.BLD)
    return filled + tip + empty + label + C.RST


def pnl_bar(profit, scale=0.001, w=BAR_W):
    """
    Directional P&L bar — green ▶ right / red ◀ left.

        ▶━━━━━━━━━━━━●─────────  +0.00012
    """
    r    = min(abs(profit) / scale, 1.0)
    f    = max(int(w * r) - 1, 0)
    col  = C.GRN if profit >= 0 else C.RED
    sign = "\u25b6" if profit >= 0 else "\u25c4"
    filled = col + sign + "\u2501" * f
    tip    = col + "\u25cf"
    empty  = C.GRY + "\u2500" * (w - f - 1)
    return filled + tip + empty + C.RST


def steps_bar(current, total, labels=None, w=None):
    """
    Step progress:  Step 1 ━━━● Step 2 ───  Step 3 ───
    current: 1-based index of active step
    """
    out = []
    for i in range(1, total + 1):
        label = (labels[i - 1] if labels and i <= len(labels)
                 else f"Krok {i}")
        if i < current:
            out.append(g(f"{label}", C.GRN) + g(" \u2501\u2501\u2501 ", C.GRN))
        elif i == current:
            out.append(g(f"\u25cf {label}", C.BLU + C.BLD) + g(" \u2500\u2500\u2500 ", C.GRY))
        else:
            out.append(g(f"{label}", C.GRY) + (g(" \u2500\u2500\u2500 ", C.GRY) if i < total else ""))
    return "".join(out)


# ── Helpers ───────────────────────────────────────────────────────────────────

def sep(char="\u2500"):
    return g(char * (W - 4), C.GRY)


def section(icon, title):
    return f"\n  {icon}  {g(title, C.BLD + C.WHT)}\n  {sep()}"


def price_arrow(curr, prev):
    if curr > prev * 1.0001: return g("\u25b2", C.GRN)
    if curr < prev * 0.9999: return g("\u25bc", C.RED)
    return g("\u2500", C.GRY)


def uptime():
    s = int(time.time() - _start_time)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


def since_fmt(secs):
    if secs is None or secs <= 0: return "-"
    if secs < 60:   return f"{int(secs)}s"
    if secs < 3600: return f"{int(secs/60)}m {int(secs%60)}s"
    return f"{int(secs/3600)}h {int((secs%3600)/60)}m"


def regime_label(regimes):
    total = sum(regimes.values())
    if not total: return g("cekam na data", C.GRY)
    dominant = max(regimes, key=regimes.get)
    pct = regimes[dominant] / total * 100
    info = {
        "BULL_TREND":  (C.GRN, "BULL TREND  silny vzestup"),
        "BEAR_TREND":  (C.RED, "BEAR TREND  silny pokles"),
        "RANGING":     (C.YLW, "RANGING     bocni pohyb"),
        "QUIET_RANGE": (C.GRY, "QUIET       bez pohybu"),
        "HIGH_VOL":    (C.MGT, "VOLATILNI   velke vykyvy"),
        "TREND":       (C.GRN, "TREND"),
        "CHOP":        (C.YLW, "CHOP  bocni"),
    }
    col, label = info.get(dominant, (C.WHT, dominant))
    return g(f"{label}  ({pct:.0f}%)", col)


# ── Status ────────────────────────────────────────────────────────────────────

def print_status():
    m   = get_metrics()
    lp  = m.get("last_prices", {})
    ls  = m.get("last_signals", {})
    ss  = m.get("sym_stats", {})
    ops = get_open_positions()
    t   = m["trades"]
    wr  = m["winrate"]

    # pre-extract to avoid backslash-in-fstring errors
    wins       = m["wins"]
    losses     = m["losses"]
    profit     = m["profit"]
    drawdown   = m["drawdown"]
    win_streak = m["win_streak"]
    los_streak = m["loss_streak"]
    conf       = m["confidence_avg"]
    gen        = m["signals_generated"]
    exe        = m["signals_executed"]
    blk        = m["blocked"]
    flt        = m["signals_filtered"]
    pf         = m.get("profit_factor", 1.0)
    exp        = m.get("expectancy", 0.0)
    best       = m.get("best_trade", 0.0)
    worst      = m.get("worst_trade", 0.0)
    since      = m.get("since_last")
    rc         = m.get("recent_count", 0)
    rwr        = m.get("recent_winrate", 0.0)
    trend      = m.get("learning_trend", "SBIRA DATA...")

    # ── Header ────────────────────────────────────────────────────────────────
    status_tag = (g(" AKTIVNI ", C.BLD + C.GRN) if m["ready"]
                  else g(" TRENINK ", C.YLW))
    print(f"\n{g('=' * W, C.CYN)}")
    print(g(f"  CRYPTOMASTER  |  {uptime()}  |{status_tag}", C.BLD + C.CYN))
    print(g("=" * W, C.CYN))

    # ── Live prices ───────────────────────────────────────────────────────────
    print(section("", "ZIVE CENY  (Binance · kazde 2 s)"))
    for sym in get_active_symbols():
        short = sym.replace("USDT", "")
        if sym not in lp:
            print(f"    {g(short, C.WHT):<4}  {g('cekam...', C.GRY)}")
            continue
        curr, prev = lp[sym]
        arr  = price_arrow(curr, prev)
        pct  = (curr - prev) / prev * 100 if prev else 0
        pcol = C.GRN if pct > 0 else (C.RED if pct < 0 else C.GRY)
        open_tag = g("  [OPEN]", C.YLW + C.BLD) if sym in ops else ""
        print(f"    {g(short, C.WHT + C.BLD):<4}  "
              f"{g(f'${curr:>14,.4f}', C.WHT)}   "
              f"{arr}  {g(f'{pct:+.3f}%', pcol)}"
              f"{open_tag}")

    # ── Open positions ────────────────────────────────────────────────────────
    if ops:
        print(section("", "OTEVRENE POZICE"))
        for sym, pos in ops.items():
            short   = sym.replace("USDT", "")
            curr    = lp.get(sym, (pos["entry"], pos["entry"]))[0]
            entry   = pos["entry"]
            action  = pos["action"]
            tp_pct  = pos["tp_move"] * 100
            sl_pct  = pos["sl_move"] * 100
            size    = pos["size"]
            move    = (curr - entry) / entry
            if action == "SELL":
                move *= -1
            pnl  = move * size
            pcol = C.GRN if pnl >= 0 else C.RED
            act  = g(action, C.GRN if action == "BUY" else C.RED)
            # Format TP/SL or Trailing Stop label
            if pos.get("is_trailing"):
                trail_sl_pct = (pos["trail_price"] * 1.5 * pos["signal"].get("atr", entry * 0.003)) / entry * 100 if entry else 0
                sl_str = g(f'🚀 TRAILING', C.CYN + C.BLD)
            else:
                sl_str = g(f'TP:{tp_pct:.2f}%  SL:{sl_pct:.2f}%', C.GRY)

            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${entry:,.4f}', C.GRY)}"
                  f"{g('->', C.GRY)}"
                  f"{g(f'${curr:,.4f}', C.WHT)}  "
                  f"{g(f'{pnl:+.6f}', pcol)}  "
                  f"{sl_str}")

    # ── Trading performance ───────────────────────────────────────────────────
    print(section("", "VYSLEDKY OBCHODOVANI"))
    if t == 0:
        print(f"    {g('Zadne uzavrene obchody – robot se zahrива...', C.GRY)}")
    else:
        w_pct   = wr * 100
        wr_col  = C.GRN if wr >= 0.55 else (C.YLW if wr >= 0.45 else C.RED)
        pr_col  = C.GRN if profit >= 0 else C.RED
        dd_col  = C.GRN if drawdown < 0.001 else (C.YLW if drawdown < 0.005 else C.RED)
        pf_col  = C.GRN if pf >= 1.5 else (C.YLW if pf >= 1.0 else C.RED)
        exp_col = C.GRN if exp > 0 else C.RED

        print(f"    {g('Obchody', C.GRY)}    {g(str(t), C.WHT + C.BLD)}  "
              f"({g(f'OK {wins}', C.GRN)}  {g(f'X {losses}', C.RED)})")

        print(f"    {g('Winrate', C.GRY)}     "
              f"{g(f'{w_pct:.1f}%', wr_col + C.BLD)}  "
              f"{cbar(wr, 1.0, lo=0.45, hi=0.55)}  "
              f"{g('cil 55%', C.GRY)}")

        print(f"    {g('Zisk', C.GRY)}        "
              f"{g(f'{profit:+.8f}', pr_col + C.BLD)}  "
              f"{pnl_bar(profit)}")

        print(f"    {g('Drawdown', C.GRY)}    "
              f"{g(f'{drawdown:.8f}', dd_col)}  "
              f"{g('(pokles od vrcholu)', C.GRY)}")

        if win_streak >= 2:
            print(f"    {g('Serie', C.GRY)}       "
                  f"{g(f'FIRE {win_streak}x vyhra v rade!', C.GRN + C.BLD)}")
        elif los_streak >= 2:
            print(f"    {g('Serie', C.GRY)}       "
                  f"{g(f'STOP {los_streak}x prohra v rade', C.RED)}")

        print(f"    {g('-' * 40, C.GRY)}")
        print(f"    {g('Profit Factor', C.GRY)}  "
              f"{g(f'{pf:.2f}x', pf_col + C.BLD)}  "
              f"{g('(zisk / ztrata, cil > 1.5)', C.GRY)}")
        print(f"    {g('Expectancy', C.GRY)}     "
              f"{g(f'{exp:+.8f}', exp_col)}  "
              f"{g('(prumerny vynos / obchod)', C.GRY)}")
        if best:
            print(f"    {g('Nejlepsi', C.GRY)}      "
                  f"{g(f'+{best:.8f}', C.GRN)}   "
                  f"{g('Nejhorsi', C.GRY)}  "
                  f"{g(f'{worst:.8f}', C.RED)}")
        if since is not None:
            print(f"    {g('Posledni obchod', C.GRY)}  "
                  f"{g(since_fmt(since), C.WHT)} {g('zpet', C.GRY)}")

    # ── Per-symbol breakdown ──────────────────────────────────────────────────
    if ss:
        print(section("", "VYSLEDKY PO MENACH"))
        print(f"    {g('Mena', C.GRY):<5}  "
              f"{g('Obch', C.GRY):>4}  "
              f"{g('WR', C.GRY):>5}  "
              f"{g('Bar', C.GRY):<20}  "
              f"{g('Zisk', C.GRY):>12}")
        print(f"    {g('-' * 50, C.GRY)}")
        for sym in get_active_symbols():
            short = sym.replace("USDT", "")
            s = ss.get(sym)
            if not s:
                print(f"    {g(short, C.GRY):<5}  {g('-', C.GRY)}")
                continue
            swr    = s["winrate"]
            str_   = s["trades"]
            swins  = s["wins"]
            sproft = s["profit"]
            wcol   = C.GRN if swr >= 0.55 else (C.YLW if swr >= 0.45 else C.RED)
            pcol   = C.GRN if sproft >= 0 else C.RED
            icon   = g("OK", C.GRN) if swr >= 0.55 else (g("?", C.YLW) if swr >= 0.45 else g("X", C.RED))
            print(f"    {g(short, C.WHT + C.BLD):<5}  "
                  f"{g(str(str_), C.WHT):>4}  "
                  f"{g(f'{swr*100:.0f}%', wcol + C.BLD):>5}  "
                  f"{cbar(swr, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g(f'{sproft:+.8f}', pcol):>12}  {icon}")

    # ── Learning ──────────────────────────────────────────────────────────────
    from src.services.learning_event import get_ev_stats, get_close_stats, get_regime_stats
    ev_st  = get_ev_stats()
    cl_st  = get_close_stats()
    rg_st  = get_regime_stats()

    print(section("", "UCENI – STAV A USPESNOST"))

    # Calibration progress
    if t >= 50:
        cal_label = g("KALIBROVAN  \u2713", C.GRN + C.BLD)
        cal_note  = g(f"({t} obchodu celkem)", C.GRY)
    else:
        cal_label = g(f"{t} / 50 obchodu", C.BLU + C.BLD)
        cal_note  = g(f"({50 - t} zbyvа)", C.GRY)
    print(f"    {g('Kalibrace', C.GRY)}      "
          f"{cal_label}  "
          f"{blue_bar(t, 50)}  "
          f"{cal_note}")

    # Learning trend + recent vs overall WR
    if t >= 10:
        tcol  = C.GRN if "ZLEP" in trend else (C.RED if "ZHOR" in trend else C.YLW)
        delta = rwr - wr
        dcol  = C.GRN if delta > 0 else C.RED
        print(f"    {g('Trend uceni', C.GRY)}    {g(trend, tcol + C.BLD)}")
        print(f"    {g(f'Poslednich {rc}', C.GRY)}    "
              f"{g(f'{rwr*100:.1f}%', C.WHT)}  vs  prumer {g(f'{wr*100:.1f}%', C.WHT)}  "
              f"{g(f'({delta:+.1%})', dcol)}")
    else:
        print(f"    {g('Sbiram data – potrebuji 50 obchodu pro plnou kalibraci.', C.GRY)}")

    # EV performance
    if ev_st["count"] > 0:
        ev_avg     = ev_st["avg"];  ev_min = ev_st["min"]
        ev_max     = ev_st["max"];  ev_cnt = ev_st["count"]
        ev_avg_col = C.GRN if ev_avg >= 0.1 else (C.YLW if ev_avg >= 0.05 else C.RED)
        print(f"    {g('EV vykon', C.GRY)}       "
              f"prumer {g(f'{ev_avg:.3f}', ev_avg_col + C.BLD)}  "
              f"min {g(f'{ev_min:.3f}', C.GRY)}  "
              f"max {g(f'{ev_max:.3f}', C.GRY)}  "
              f"{g(f'({ev_cnt} obch)', C.GRY)}")
    else:
        print(f"    {g('EV vykon', C.GRY)}       {g('zadna data', C.GRY)}")

    # Close-reason breakdown
    total_cl = sum(v["n"] for v in cl_st.values())
    if total_cl > 0:
        tp_pct  = cl_st["TP"]["pct"];      sl_pct  = cl_st["SL"]["pct"]
        tr_pct  = cl_st["trail"]["pct"];   to_pct  = cl_st["timeout"]["pct"]
        tp_col  = C.GRN if tp_pct >= 40 else C.YLW
        sl_col  = C.RED if sl_pct >= 40 else C.YLW
        tr_col  = C.GRN if tr_pct >= 10 else C.GRY
        to_col  = C.RED if to_pct >= 30 else C.YLW
        print(f"    {g('Uzavreni', C.GRY)}       "
              f"TP {g(f'{tp_pct:.0f}%', tp_col + C.BLD)}  "
              f"SL {g(f'{sl_pct:.0f}%', sl_col)}  "
              f"trail {g(f'{tr_pct:.0f}%', tr_col)}  "
              f"timeout {g(f'{to_pct:.0f}%', to_col)}")
    else:
        print(f"    {g('Uzavreni', C.GRY)}       {g('zadna data', C.GRY)}")

    # Win-prob calibration quality: avg conf vs actual WR
    if t >= 5:
        cal_drift = abs(conf - wr)
        cal_col   = C.GRN if cal_drift < 0.08 else (C.YLW if cal_drift < 0.15 else C.RED)
        cal_note2 = "dobre" if cal_drift < 0.08 else ("ok" if cal_drift < 0.15 else "odkalibrovan")
        print(f"    {g('Kalibrace p', C.GRY)}    "
              f"p={g(f'{conf*100:.1f}%', C.WHT)}  WR={g(f'{wr*100:.1f}%', C.WHT)}  "
              f"odchylka {g(f'{cal_drift*100:.1f}pp', cal_col + C.BLD)}  "
              f"{g(cal_note2, cal_col)}")

    # Regime-specific WR table
    if rg_st:
        print(f"    {g('WR dle rezimu', C.GRY)}")
        regime_order = ["BULL_TREND", "BEAR_TREND", "RANGING", "QUIET_RANGE", "HIGH_VOL"]
        for reg in regime_order:
            if reg not in rg_st: continue
            rs   = rg_st[reg]
            rwr2 = rs["winrate"]
            rcol = C.GRN if rwr2 >= 0.55 else (C.YLW if rwr2 >= 0.45 else C.RED)
            label = {"BULL_TREND": "BULL ", "BEAR_TREND": "BEAR ",
                     "RANGING": "RANGE", "QUIET_RANGE": "QUIET", "HIGH_VOL": "HVOL "}.get(reg, reg[:5])
            rnt = rs["trades"]
            print(f"      {g(label, C.WHT + C.BLD)}  "
                  f"{cbar(rwr2, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g(f'{rwr2*100:.0f}%', rcol + C.BLD)}  "
                  f"{g(f'({rnt} obch)', C.GRY)}")

    # ── Auditor status ────────────────────────────────────────────────────────
    from bot2.auditor import is_in_cooldown, get_position_size_mult
    from src.services.learning_event import trades_in_window, trades_per_hour
    in_cd    = is_in_cooldown()
    sz_mult  = get_position_size_mult()
    t15      = trades_in_window(900)
    t1h      = trades_per_hour()
    ev_thr   = 0.0
    if t15 > 10: ev_thr = min(0.05, ev_thr + 0.005)
    ev_col   = C.GRN if ev_thr == 0.0 else C.YLW
    sz_col   = C.GRN if sz_mult >= 1.0 else (C.YLW if sz_mult >= 0.5 else C.RED)
    cd_tag   = g("  COOLDOWN", C.RED + C.BLD) if in_cd else g("  aktivni", C.GRN)
    print(section("", "AUDITOR  (ochrana strategie)"))
    print(f"    {g('EV prah', C.GRY)}              "
          f"{g(f'{ev_thr:.3f}', ev_col + C.BLD)}  "
          f"{g(f't15={t15}  t60={t1h}', C.GRY)}"
          f"{cd_tag}")
    print(f"    {g('Velikost pozice', C.GRY)}      "
          f"{g(f'{sz_mult:.2f}x', sz_col + C.BLD)}  "
          f"{g('EV-only · loss streak → scale · DD halt 40%', C.GRY)}")

    # ── Strategy / Signals ────────────────────────────────────────────────────
    print(section("", "STRATEGIE  (ADX + EMA + MACD + BB + RSI)"))

    passed = max(0, gen - flt - blk)
    eff = passed / gen * 100 if gen else 0
    eff_col = C.GRN if eff > 2 else C.YLW

    print(f"    {g('Rezim trhu', C.GRY)}   {regime_label(m['regimes'])}")
    print(f"    {g('Signaly', C.GRY)}       "
          f"{g(str(gen), C.WHT)} zachyceno  "
          f"{g(str(gen - flt), C.WHT)} po filtru  "
          f"{g(str(blk), C.RED)} blokovano  "
          f"{g(str(exe), C.GRN)} provedeno")
    print(f"    {g('Filtrace', C.GRY)}      "
          f"{g(f'{eff:.1f}%', eff_col)}  "
          f"{g('projde filtrem', C.GRY)}  "
          f"{g('TP: 1.2xATR  /  SL: 0.8xATR  (RR 1.5:1)  EV-only', C.GRY)}")

    # ── Last signals ──────────────────────────────────────────────────────────
    if ls:
        print(section("", "POSLEDNI ROZHODNUTI"))
        for sym in get_active_symbols():
            short = sym.replace("USDT", "")
            if sym not in ls:
                print(f"    {g(short, C.WHT + C.BLD):<4}  {g('zadny signal', C.GRY)}")
                continue
            sig    = ls[sym]
            action = sig["action"]
            sprice = sig["price"]
            sconf  = sig["confidence"] * 100
            sev    = sig.get("ev", 0)
            sreg   = sig.get("regime", "")
            res    = sig.get("result")
            is_buy = action == "BUY"
            act    = g("KUPUJ ", C.GRN + C.BLD) if is_buy else g("PRODEJ", C.RED + C.BLD)
            rtag   = (g("  VYHRA",  C.GRN + C.BLD) if res == "WIN"
                      else g("  PROHRA", C.RED + C.BLD) if res == "LOSS" else "")
            ev_tag = g(f"  ev:{sev:.3f}", C.CYN) if sev else ""
            reg_short = {"BULL_TREND": "BULL", "BEAR_TREND": "BEAR",
                         "RANGING": "RANGE", "QUIET_RANGE": "QUIET"}.get(sreg, sreg[:5])
            print(f"    {g(short, C.WHT + C.BLD):<4}  {act}  "
                  f"{g(f'${sprice:,.4f}', C.WHT)}  "
                  f"{g(f'p:{sconf:.0f}%', C.GRY)}"
                  f"{ev_tag}  {g(reg_short, C.GRY)}"
                  f"{rtag}")

    # ── Footer ────────────────────────────────────────────────────────────────
    # 3-step progress: Sbírám data → Trénink → Aktivní
    if m["ready"]:
        step = 3
    elif t >= 50:
        step = 2
    else:
        step = 1
    print(f"\n  {sep()}")
    print(f"  {steps_bar(step, 3, ['Sbiram data', 'Trenink', 'Aktivni'])}")
    print(f"  {sep()}")
    if m["ready"]:
        print(f"  {g('STAV:', C.BLD)}  "
              f"{g('AKTIVNI – robot je kalibrovany a obchoduje!', C.GRN + C.BLD)}")
    else:
        needs = []
        if t < 50:      needs.append(g(f"obchody {t}/50", C.YLW))
        if wr <= 0.55:  needs.append(g(f"winrate {wr*100:.0f}%->55%", C.YLW))
        if profit <= 0: needs.append(g("zisk > 0", C.YLW))
        joined = ",  ".join(needs)
        print(f"  {g('STAV:', C.BLD)}  {g('TRENINK', C.YLW + C.BLD)}  "
              f"{g('(', C.GRY)}{joined}{g(')', C.GRY)}")
    print(g("=" * W, C.CYN) + "\n")


# ── Pre-live audit (periodic health check, replay from Firestore) ─────────────

def _run_pre_live_audit() -> None:
    """
    Run pre_live_audit in replay mode every PRE_AUDIT_INTERVAL seconds.

    Replays the last 20 closed trades through the full sizing chain, checks
    invariants, and publishes a summary to Firebase (audit/latest).
    Non-blocking: any exception is caught and logged; bot loop continues.
    """
    try:
        from src.services.pre_live_audit import run_audit as _pa_run
        print("\n[bot2] ── pre_live_audit ─────────────────────────────────────")
        results, ci_pass = _pa_run(
            n_trades = 20,
            verbose  = False,   # quiet — summary only in bot2 log
            seed     = 42,
            replay   = True,    # use real closed trades from Firestore
        )
        # ── Publish audit summary to Firebase for observability ───────────────
        try:
            from src.services.firebase_client import get_db
            _db = get_db()
            if _db is not None:
                _passed  = [r for r in results if r.passed]
                _sizes   = [r.s_final     for r in _passed]
                _rbs     = [r.risk_budget for r in _passed]
                _blocked = len(results) - len(_passed)
                _mono_v  = sum(len(r.monotone_violations) for r in results)
                _summary = {
                    "ci_pass":             ci_pass,
                    "timestamp":           time.time(),
                    "mode":                "replay",
                    "total_trades":        len(results),
                    "blocked_trades":      _blocked,
                    "blocked_ratio":       round(_blocked / max(len(results), 1), 4),
                    "monotone_violations": _mono_v,
                    "avg_size":            round(sum(_sizes) / max(len(_sizes), 1), 6),
                    "avg_risk_budget":     round(sum(_rbs)   / max(len(_rbs),   1), 4),
                }
                _db.document("audit/latest").set(_summary)
        except Exception as _fb_exc:
            print(f"[bot2] audit Firebase publish skipped: {_fb_exc}")

        status = "PASS" if ci_pass else "FAIL"
        print(f"[bot2] pre_live_audit complete  ci={status}")
        print("[bot2] ─────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"[bot2] pre_live_audit skipped: {exc.__class__.__name__}: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_firebase()
    daily_budget_report()

    _history = load_history()

    # DB-vanish detection: Firebase connected but zero trades returned.
    # Could be a genuine first run or a collection wipe.  Either way, the
    # bot enters bootstrap mode (trades=0 < 150 threshold) automatically.
    # Log clearly so the Railway log makes the cause obvious.
    if _history is not None and len(_history) == 0:
        print("⚠️  [DB_WIPE] Firebase returned 0 trades — starting in full bootstrap mode. "
              "Session gate bypassed, debounce bypassed, force-trade guard active.")

    bootstrap_from_history(_history)
    warmup()

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    while True:
        time.sleep(10)

        global _last_audit, _last_metrics, _last_pre_audit
        now = time.time()

        if now - _last_audit >= AUDIT_INTERVAL:
            run_audit()
            _last_audit = now

        if now - _last_metrics >= METRICS_INTERVAL:
            _pos = get_open_positions()
            execution_data = None
            try:
                from src.services.dashboard_live import dashboard_snapshot, dashboard_metrics
                snap  = dashboard_snapshot(_pos)
                met   = dashboard_metrics()
                fscore = float(snap.get("failure", 0.0))
                # Serialise symbols dict: round float values for Firestore
                syms = {
                    sym: {"ev": round(float(v["ev"]), 5),
                          "size": round(float(v["size"]), 5),
                          "reg": str(v["reg"])}
                    for sym, v in snap.get("symbols", {}).items()
                }
                execution_data = {
                    "equity":       round(float(snap.get("equity",   1.0)), 6),
                    "drawdown":     round(float(snap.get("drawdown", 0.0)), 6),
                    "exposure":     round(float(snap.get("exposure", 0.0)), 4),
                    "failure_score": round(fscore, 3),
                    "control":      "HALT" if fscore > 3.0 else "WARN" if fscore > 1.5 else "OK",
                    "sharpe":       round(float(met.get("sharpe",   0.0)), 4),
                    "avg_edge":     round(float(met.get("avg_edge", 0.0)), 6),
                    "exec_winrate": round(float(met.get("winrate",  0.0)), 4),
                    "max_dd":       round(float(met.get("max_dd",   0.0)), 4),
                    "symbols":      syms,
                }
            except Exception as _ex:
                pass

            monitor_data = None
            try:
                from src.services.learning_monitor import lm_snapshot
                monitor_data = lm_snapshot()
            except Exception:
                pass

            save_metrics_full(get_metrics(), _pos,
                              execution=execution_data,
                              monitor=monitor_data)
            _last_metrics = now

        if now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
            _run_pre_live_audit()
            _last_pre_audit = now

        try:
            from src.services.learning_monitor import meta_update
            meta_update()
        except Exception:
            pass

        print_status()
        dashboard_loop(get_open_positions())

        try:
            from src.services.learning_monitor import print_learning_monitor
            print_learning_monitor()
        except Exception:
            pass


if __name__ == "__main__":
    main()
