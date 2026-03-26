import threading, time

from src.services.market_stream import start
from src.services.firebase_client import init_firebase
from src.services.learning_event import get_metrics

import src.services.signal_generator
import src.services.trade_executor

_start_time = time.time()
SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def bar(value, max_val=1.0, width=12):
    filled = int(width * min(max(value / max_val, 0), 1.0))
    return "█" * filled + "░" * (width - filled)


def price_arrow(curr, prev):
    if curr > prev * 1.0001: return "▲"
    if curr < prev * 0.9999: return "▼"
    return "─"


def regime_label(regimes):
    total = sum(regimes.values())
    if total == 0:
        return "čekám na data"
    dominant = max(regimes, key=regimes.get)
    pct = regimes[dominant] / total * 100
    labels = {
        "TREND":    "TREND – směrový pohyb",
        "CHOP":     "CHOP – boční trh",
        "HIGH_VOL": "VOLATILNÍ – velké výkyvy",
    }
    return f"{labels.get(dominant, dominant)} ({pct:.0f}%)"


def uptime():
    secs = int(time.time() - _start_time)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s"


def learning_progress_bar(t, target=50):
    """Visual progress toward the 50-trade calibration target."""
    pct = min(t / target, 1.0)
    return f"[{bar(pct, 1.0, 20)}] {t}/{target}"


# ── Main status print ─────────────────────────────────────────────────────────

def print_status():
    m   = get_metrics()
    lp  = m.get("last_prices", {})
    ls  = m.get("last_signals", {})
    ss  = m.get("sym_stats", {})
    t   = m["trades"]
    wr  = m["winrate"]
    sep = "─" * 54

    print(f"\n{'═'*54}")
    print(f"  🤖  CRYPTOMASTER  │  běží {uptime()}")
    print(f"{'═'*54}")

    # ── Live prices ──────────────────────────────────────────
    print(f"\n  💰  ŽIVÉ CENY  (Binance, každé 2 s)")
    print(f"  {sep}")
    for sym in SYMBOLS:
        short = sym.replace("USDT", "")
        if sym in lp:
            curr, prev = lp[sym]
            arr  = price_arrow(curr, prev)
            pct  = (curr - prev) / prev * 100 if prev else 0
            sign = "+" if pct >= 0 else ""
            print(f"    {short:<4}  ${curr:>14,.4f}   {arr}  {sign}{pct:.3f}%")
        else:
            print(f"    {short:<4}  čekám na tick...")

    # ── Trading performance ───────────────────────────────────
    print(f"\n  📈  VÝSLEDKY OBCHODOVÁNÍ")
    print(f"  {sep}")
    if t == 0:
        print("    Zatím žádné uzavřené obchody.")
        print("    Robot čeká na první signál s dostatečnou jistotou.")
    else:
        print(f"    Celkem obchodů :  {t}")
        print(f"    ✅ Výhry         :  {m['wins']}    ❌ Prohry: {m['losses']}")
        print(f"    Winrate          :  {wr*100:.1f}%   [{bar(wr)}]")
        print(f"    Celkový zisk     : {m['profit']:+.6f} USDT")
        print(f"    Max. drawdown    :  {m['drawdown']:.6f}  (největší pokles od vrcholu)")
        if m["win_streak"] >= 2:
            print(f"    Série            : 🔥 {m['win_streak']}× výhra v řadě!")
        elif m["loss_streak"] >= 2:
            print(f"    Série            : 💔 {m['loss_streak']}× prohra v řadě")

    # ── Per-symbol breakdown ──────────────────────────────────
    if ss:
        print(f"\n  📊  VÝSLEDKY PO MĚNÁCH")
        print(f"  {sep}")
        print(f"    {'Měna':<6} {'Obchody':>8} {'Výhry':>6} {'WR':>7} {'Zisk':>12}")
        print(f"    {'─'*6} {'─'*8} {'─'*6} {'─'*7} {'─'*12}")
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            s = ss.get(sym, {})
            if not s:
                print(f"    {short:<6} {'–':>8}")
                continue
            swr = s.get("winrate", 0)
            print(
                f"    {short:<6} {s['trades']:>8} {s['wins']:>6} "
                f"{swr*100:>6.1f}%  {s['profit']:>+11.6f}"
            )

    # ── Learning progress ─────────────────────────────────────
    print(f"\n  🧠  JAK SE ROBOT UČÍ")
    print(f"  {sep}")
    print(f"    Progres trénování : {learning_progress_bar(t)}")

    rc    = m.get("recent_count", 0)
    rwr   = m.get("recent_winrate", 0)
    trend = m.get("learning_trend", "SBÍRÁ DATA...")
    conf  = m["confidence_avg"]

    if t < 10:
        print("    Sbírám první obchody – potřebuji alespoň 50 pro plnou kalibraci.")
        print("    Každý obchod zlepšuje schopnost filtrovat špatné vzory.")
    else:
        print(f"    Trend učení       : {trend}")
        print(f"    Posledních {rc:>2} obch.: {rwr*100:.1f}%  vs. celkový průměr {wr*100:.1f}%")
        delta = rwr - wr
        if abs(delta) >= 0.02:
            direction = "lepší" if delta > 0 else "horší"
            print(f"      → Robot je momentálně o {abs(delta)*100:.1f}% {direction} než celkový průměr.")

    conf_label = "nízká – hledám silnější vzory" if conf < 0.3 else \
                 ("střední – robot si věří" if conf < 0.6 else "vysoká – jasný signál ✅")
    print(f"    Průměrná jistota  : [{bar(conf)}] {conf*100:.1f}%")
    print(f"      → {conf_label}")

    # ── Signals ───────────────────────────────────────────────
    print(f"\n  📡  SIGNÁLY A FILTRY")
    print(f"  {sep}")
    gen = m["signals_generated"]
    exe = m["signals_executed"]
    blk = m["blocked"]
    flt = m["signals_filtered"]
    eff = exe / gen * 100 if gen else 0
    print(f"    Zachyceno cen     :  {gen}")
    print(f"    Po EMA/RSI filtru :  {gen - flt}")
    print(f"    Blokováno AI      :  {blk}   (špatné historické vzory)")
    print(f"    Provedeno         :  {exe}")
    print(f"    Efektivita        :  {eff:.1f}%")
    print(f"    Režim trhu        :  {regime_label(m['regimes'])}")

    # ── Last decision per symbol ──────────────────────────────
    if ls:
        print(f"\n  ⚡  POSLEDNÍ ROZHODNUTÍ ROBOTA")
        print(f"  {sep}")
        for sym in SYMBOLS:
            short = sym.replace("USDT", "")
            if sym in ls:
                sig = ls[sym]
                act = "🟢 KUPUJ" if sig["action"] == "BUY" else "🔴 PRODEJ"
                res = {"WIN": "  → ✅ VÝHRA", "LOSS": "  → ❌ PROHRA"}.get(sig.get("result"), "")
                print(f"    {short:<4}  {act}  ${sig['price']:,.4f}  "
                      f"jistota {sig['confidence']*100:.0f}%{res}")
            else:
                print(f"    {short:<4}  ⚪ žádný signál zatím")

    # ── Overall status ────────────────────────────────────────
    print(f"\n  {sep}")
    if m["ready"]:
        print("  🎯  STAV: ✅ AKTIVNÍ – robot je kalibrovaný a obchoduje!")
    else:
        needs = []
        if t < 50:            needs.append(f"obchody {t}/50")
        if wr <= 0.55:        needs.append(f"winrate {wr*100:.0f}%→55%")
        if m["profit"] <= 0:  needs.append("zisk > 0")
        print(f"  🎯  STAV: 🔄 TRÉNINK  ({',  '.join(needs)})")
        print("        Robot ladí strategii na živých datech.")
    print(f"{'═'*54}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_firebase()

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    while True:
        time.sleep(10)
        print_status()


if __name__ == "__main__":
    main()
