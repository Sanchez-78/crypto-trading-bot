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


# ── Helpers ──────────────────────────────────────────────────────────────────

def bar(value, max_val=1.0, width=12):
    filled = int(width * min(max(value / max_val, 0.0), 1.0))
    return "█" * filled + "░" * (width - filled)


def price_arrow(curr, prev):
    if curr > prev * 1.0001: return "▲"
    if curr < prev * 0.9999: return "▼"
    return "─"


def uptime():
    secs = int(time.time() - _start_time)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


def regime_label(regimes):
    total = sum(regimes.values())
    if total == 0:
        return "čekám na data"
    dominant = max(regimes, key=regimes.get)
    pct = regimes[dominant] / total * 100
    icons = {
        "BULL_TREND": "📈 BULL TREND – silný vzestup",
        "BEAR_TREND": "📉 BEAR TREND – silný pokles",
        "RANGING":    "↔️  RANGING – boční pohyb",
        "QUIET_RANGE":"😴 QUIET – žádný pohyb",
        "HIGH_VOL":   "⚡ VOLATILNÍ – velké výkyvy",
        "TREND":      "📈 TREND",
        "CHOP":       "↔️  CHOP – boční",
    }
    return f"{icons.get(dominant, dominant)} ({pct:.0f}%)"


def progress_bar(t, target=50):
    pct = min(t / target, 1.0)
    return f"[{bar(pct, 1.0, 20)}] {t}/{target}"


# ── Status print ─────────────────────────────────────────────────────────────

def print_status():
    m    = get_metrics()
    lp   = m.get("last_prices", {})
    ls   = m.get("last_signals", {})
    ss   = m.get("sym_stats", {})
    ops  = get_open_positions()
    t    = m["trades"]
    wr   = m["winrate"]
    SEP  = "─" * 54

    print(f"\n{'═'*54}")
    print(f"  🤖  CRYPTOMASTER  │  běží {uptime()}")
    print(f"{'═'*54}")

    # ── Live prices ──────────────────────────────────────────
    print(f"\n  💰  ŽIVÉ CENY  (Binance, každé 2 s)")
    print(f"  {SEP}")
    for sym in SYMBOLS:
        short = sym.replace("USDT", "")
        if sym in lp:
            curr, prev = lp[sym]
            arr  = price_arrow(curr, prev)
            pct  = (curr - prev) / prev * 100 if prev else 0
            sign = "+" if pct >= 0 else ""
            pos_flag = " 🔄 OPEN" if sym in ops else ""
            print(f"    {short:<4}  ${curr:>14,.4f}   {arr}  {sign}{pct:.3f}%{pos_flag}")
        else:
            print(f"    {short:<4}  čekám na první tick...")

    # ── Open positions ────────────────────────────────────────
    if ops:
        print(f"\n  🔄  OTEVŘENÉ POZICE  (čekají na TP/SL)")
        print(f"  {SEP}")
        for sym, pos in ops.items():
            short = sym.replace("USDT", "")
            curr  = lp.get(sym, (pos["entry"], pos["entry"]))[0]
            move  = (curr - pos["entry"]) / pos["entry"]
            if pos["action"] == "SELL":
                move *= -1
            pnl  = move * pos["size"]
            icon = "📈" if move > 0 else "📉"
            tp   = pos["tp_move"] * 100
            sl   = pos["sl_move"] * 100
            print(f"    {short:<4}  {pos['action']}  "
                  f"${pos['entry']:,.4f}→${curr:,.4f}  "
                  f"{icon} {pnl:+.6f}  "
                  f"[TP:{tp:.2f}%  SL:{sl:.2f}%]")

    # ── Trading performance ───────────────────────────────────
    print(f"\n  📈  VÝSLEDKY OBCHODOVÁNÍ")
    print(f"  {SEP}")
    if t == 0:
        print("    Žádné uzavřené obchody. Robot se zahřívá (50 ticků warmup).")
    else:
        print(f"    Celkem uzavřeno :  {t}")
        print(f"    ✅ Výhry         :  {m['wins']}    ❌ Prohry: {m['losses']}")
        print(f"    Winrate          :  {wr*100:.1f}%   [{bar(wr)}]")
        print(f"    Celkový zisk     : {m['profit']:+.6f} USDT")
        print(f"    Max. drawdown    :  {m['drawdown']:.6f}")
        if m["win_streak"] >= 2:
            print(f"    Série            : 🔥 {m['win_streak']}× výhra v řadě!")
        elif m["loss_streak"] >= 2:
            print(f"    Série            : 💔 {m['loss_streak']}× prohra v řadě")

    # ── Per-symbol breakdown ──────────────────────────────────
    if ss:
        print(f"\n  📊  VÝSLEDKY PO MĚNÁCH")
        print(f"  {SEP}")
        print(f"    {'Měna':<5} {'Obchody':>8} {'Výhry':>6} {'WR':>7} {'Zisk':>12}  {'Stav'}")
        print(f"    {'─'*5} {'─'*8} {'─'*6} {'─'*7} {'─'*12}  {'─'*8}")
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            s = ss.get(sym)
            if not s:
                print(f"    {short:<5} {'–':>8}")
                continue
            swr  = s["winrate"]
            icon = "✅" if swr >= 0.55 else ("⚠️" if swr >= 0.45 else "❌")
            print(f"    {short:<5} {s['trades']:>8} {s['wins']:>6} "
                  f"{swr*100:>6.1f}%  {s['profit']:>+11.6f}  {icon}")

    # ── Learning progress ─────────────────────────────────────
    print(f"\n  🧠  UČENÍ  –  JAK ROBOT ROSTE")
    print(f"  {SEP}")
    print(f"    Kalibrační progres : {progress_bar(t)}")

    rc    = m.get("recent_count", 0)
    rwr   = m.get("recent_winrate", 0.0)
    trend = m.get("learning_trend", "SBÍRÁ DATA...")
    conf  = m["confidence_avg"]

    if t < 10:
        print("    Robot sbírá data. Po 50 obchodech se plně kalibruje.")
        print("    Každý obchod učí rozlišovat dobré a špatné vzory trhu.")
    else:
        print(f"    Trend učení         : {trend}")
        delta = rwr - wr
        print(f"    Posledních {rc:>2} obch. : {rwr*100:.1f}%  (celkový průměr {wr*100:.1f}%)")
        if abs(delta) >= 0.02:
            direction = "lepší" if delta > 0 else "horší"
            print(f"      → Robot je nyní o {abs(delta)*100:.1f}% {direction} než svůj celkový průměr.")

    conf_note = (
        "nízká – hledám silné vzory" if conf < 0.3 else
        "střední – robot vidí příležitosti" if conf < 0.6 else
        "vysoká – jasné signály ✅"
    )
    print(f"    Průměrná jistota    : [{bar(conf)}] {conf*100:.1f}%  ({conf_note})")

    # ── Strategy info ─────────────────────────────────────────
    print(f"\n  ⚙️   STRATEGIE  (multi-indikátor, ADX + EMA + MACD + BB + RSI)")
    print(f"  {SEP}")
    print(f"    Režim trhu   : {regime_label(m['regimes'])}")
    gen = m["signals_generated"]
    exe = m["signals_executed"]
    blk = m["blocked"]
    flt = m["signals_filtered"]
    eff = exe / gen * 100 if gen else 0
    print(f"    Signály      : {gen} zachyceno → {gen-flt} po filtru → {blk} blokováno AI → {exe} provedeno")
    print(f"    Efektivita   : {eff:.1f}%  (kolik prošlo celým filtrem)")
    print(f"    TP:SL ratio  : 2.0×ATR TP  /  1.5×ATR SL  (RR ≈ 1.33:1)")

    # ── Last decisions ────────────────────────────────────────
    if ls:
        print(f"\n  ⚡  POSLEDNÍ ROZHODNUTÍ")
        print(f"  {SEP}")
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            if sym in ls:
                sig = ls[sym]
                act = "🟢 KUPUJ" if sig["action"] == "BUY" else "🔴 PRODEJ"
                res = {"WIN": "  → ✅ VÝHRA", "LOSS": "  → ❌ PROHRA"}.get(sig.get("result"), "")
                print(f"    {short:<4}  {act}  ${sig['price']:,.4f}  "
                      f"jistota {sig['confidence']*100:.0f}%{res}")
            else:
                print(f"    {short:<4}  ⚪ žádný signál")

    # ── Status ────────────────────────────────────────────────
    print(f"\n  {SEP}")
    if m["ready"]:
        print("  🎯  STAV: ✅ AKTIVNÍ – robot je kalibrovaný a obchoduje!")
    else:
        needs = []
        if t < 50:            needs.append(f"obchody {t}/50")
        if wr <= 0.55:        needs.append(f"winrate {wr*100:.0f}%→55%")
        if m["profit"] <= 0:  needs.append("zisk > 0")
        print(f"  🎯  STAV: 🔄 TRÉNINK  ({',  '.join(needs)})")
        print("        Robot automaticky zlepšuje parametry na živých datech.")
    print(f"{'═'*54}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_firebase()
    daily_budget_report()

    # Restore historical state so bot doesn't start from zero after restart
    bootstrap_from_history(load_history())

    # Pre-warm price indicators from Binance klines (skip 5-min tick warmup)
    warmup()

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    while True:
        time.sleep(10)
        print_status()


if __name__ == "__main__":
    main()
