"""V5 Bot Czech Dashboard — real-time metrics display matching legacy bot format.

Prints continuous metrics similar to bot2/main.py print_status() in Czech.
"""

import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ANSI color codes
class C:
    RED = "\033[31m"
    GRN = "\033[32m"
    YLW = "\033[33m"
    BLU = "\033[34m"
    CYN = "\033[36m"
    WHT = "\033[37m"
    GRY = "\033[90m"
    BLD = "\033[1m"
    RST = "\033[0m"


def g(text: str, color: str = "") -> str:
    """Colorize text. g = green (default), color override with C.* constants."""
    if not color:
        color = C.GRN
    return f"{color}{text}{C.RST}"


def section(prefix: str, title: str) -> str:
    """Format section header."""
    return f"\n{g(title, C.BLD + C.CYN)}"


def cbar(value: float, max_val: float, lo: float = 0.45, hi: float = 0.55, width: int = 20) -> str:
    """Create colored bar (0-max_val scale with lo/hi zones)."""
    if max_val <= 0:
        return g("─" * width, C.GRY)

    filled = int((value / max_val) * width)
    filled = max(0, min(width, filled))

    if lo == 0:
        # Simple bar
        bar = "━" * filled + "─" * (width - filled)
        return g(bar, C.CYN)

    # Three-zone bar (red-yellow-green)
    lo_width = int(lo * width)
    hi_width = int(hi * width)

    if filled <= lo_width:
        color = C.RED
    elif filled <= hi_width:
        color = C.YLW
    else:
        color = C.GRN

    bar = "━" * filled + "─" * (width - filled)
    return g(bar, color)


def blue_bar(value: float, max_val: float, width: int = 20) -> str:
    """Create blue progress bar."""
    if max_val <= 0:
        return g("─" * width, C.GRY)

    filled = int((value / max_val) * width)
    filled = max(0, min(width, filled))
    bar = "━" * filled + "─" * (width - filled)
    return g(bar, C.BLU)


def pnl_bar(value: float) -> str:
    """Create profit/loss bar."""
    if value >= 0:
        return g("✓", C.GRN)
    else:
        return g("✗", C.RED)


def price_arrow(curr: float, prev: float) -> str:
    """Show price direction arrow."""
    if curr > prev:
        return g("↑", C.GRN)
    elif curr < prev:
        return g("↓", C.RED)
    else:
        return g("→", C.GRY)


@dataclass
class TradeStats:
    """Summary of trades by symbol."""
    symbol: str
    count: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    total_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    @property
    def win_rate(self) -> Optional[float]:
        """Win rate (wins / (wins + losses), excluding flats)."""
        decisive = self.wins + self.losses
        return self.wins / decisive if decisive > 0 else None

    @property
    def avg_pnl(self) -> float:
        """Average PnL per trade."""
        return self.total_pnl / self.count if self.count > 0 else 0.0


class CzechDashboard:
    """V5 Bot metrics printer — Czech format."""

    def __init__(self, trading_symbols: List[str]):
        self.trading_symbols = trading_symbols
        self.W = 80  # Console width

    def compute_stats(self, closed_trades: Dict[str, Any]) -> tuple:
        """Compute trading statistics from closed trades."""
        stats = {
            "trades_total": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "net_pnl": 0.0,
            "per_symbol": defaultdict(lambda: TradeStats("")),
        }

        for trade_id, trade in closed_trades.items():
            pnl = trade.get("net_pnl_pct", 0) if isinstance(trade, dict) else trade.net_pnl_pct

            # Total
            stats["trades_total"] += 1
            stats["net_pnl"] += trade.get("net_pnl_usd", 0) if isinstance(trade, dict) else trade.net_pnl_usd

            # Outcome
            if pnl > 0:
                stats["wins"] += 1
            elif pnl < 0:
                stats["losses"] += 1
            else:
                stats["flats"] += 1

            # Per symbol
            symbol = trade.get("symbol") if isinstance(trade, dict) else trade.symbol
            if symbol:
                ts = stats["per_symbol"][symbol]
                ts.symbol = symbol
                ts.count += 1
                ts.total_pnl += trade.get("net_pnl_usd", 0) if isinstance(trade, dict) else trade.net_pnl_usd

                if pnl > 0:
                    ts.wins += 1
                    ts.best_trade = max(ts.best_trade, pnl)
                elif pnl < 0:
                    ts.losses += 1
                    ts.worst_trade = min(ts.worst_trade, pnl)
                else:
                    ts.flats += 1

        return stats, stats["per_symbol"]

    def print_header(self, status_tag: str = "AKTIVNI") -> None:
        """Print dashboard header."""
        print(f"\n{g('=' * self.W, C.CYN)}")
        tag_color = C.BLD + C.GRN if status_tag == "AKTIVNI" else C.BLD + C.YLW
        print(g(f"  V5 PAPER BOT  |  {status_tag}", tag_color))
        print(g("=" * self.W, C.CYN))

    def print_trading_performance(self, closed_trades: Dict[str, Any],
                                 entries_attempted: int, entries_successful: int,
                                 entries_rejected: int, trades_closed: int,
                                 open_positions: int = 0, open_notional: float = 0.0) -> None:
        """Print trading performance metrics."""
        stats, per_sym = self.compute_stats(closed_trades)

        t = stats["trades_total"]
        wins = stats["wins"]
        losses = stats["losses"]
        flats = stats["flats"]
        profit = stats["net_pnl"]

        print(section("", "VYSLEDKY OBCHODOVANI"))

        # Entry attempt statistics (always show)
        print(f"    {g('Pokusy vstupu', C.GRY)}")
        print(f"      Pokusů    {g(str(entries_attempted), C.WHT + C.BLD)}")
        print(f"      Úspěšných {g(str(entries_successful), C.GRN + C.BLD)}")
        print(f"      Odmítnuto  {g(str(entries_rejected), C.YLW)}")

        # Open positions
        open_col = C.BLU if open_positions > 0 else C.GRY
        print(f"    {g('Otevřené pozice', C.GRY)}  {g(str(open_positions), open_col + C.BLD)}  "
              f"(${open_notional:+.2f})")

        print(f"    {g('-' * 40, C.GRY)}")

        # Closed trades statistics
        if t == 0:
            print(f"    {g('Uzavřené obchody', C.GRY)}     {g('0', C.GRY)} – robot se zahřívá")
        else:
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0.0
            w_pct = wr * 100

            wr_col = C.GRN if wr >= 0.55 else (C.YLW if wr >= 0.45 else C.RED)
            pr_col = C.GRN if profit >= 0 else C.RED

            print(f"    {g('Obchody', C.GRY)}    {g(str(t), C.WHT + C.BLD)}  "
                  f"({g(f'OK {wins}', C.GRN)}  {g(f'X {losses}', C.RED)}  "
                  f"{g(f'~ {flats}', C.GRY)})")

            print(f"    {g('WR', C.GRY)}          "
                  f"{g(f'{w_pct:.1f}%', wr_col + C.BLD)}  "
                  f"{cbar(wr, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g('cíl 55%', C.GRY)}")

            print(f"    {g('Zisk (PnL)', C.GRY)}    "
                  f"{g(f'{profit:+.8f}', pr_col + C.BLD)}  "
                  f"{pnl_bar(profit)}")

        print(f"    {g('Uzavřeno dnes', C.GRY)}      {g(str(trades_closed), C.WHT)}")

    def print_open_positions(self, open_positions: Dict[str, Any]) -> None:
        """Print currently open positions."""
        if not open_positions:
            return

        print(section("", "OTEVŘENE POZICE"))
        print(f"    {g('Mena', C.GRY):<6}  "
              f"{g('Strana', C.GRY):>5}  "
              f"{g('Qty', C.GRY):>6}  "
              f"{g('Vstup', C.GRY):>10}  "
              f"{g('TP', C.GRY):>10}  "
              f"{g('SL', C.GRY):>10}")
        print(f"    {g('-' * 60, C.GRY)}")

        for trade_id, position in open_positions.items():
            short = position.symbol.replace("USDT", "")
            side_str = g(position.side, C.GRN) if position.side == "BUY" else g(position.side, C.RED)

            print(f"    {g(short, C.WHT + C.BLD):<6}  "
                  f"{side_str:>5}  "
                  f"{g(f'{position.qty:.3f}', C.WHT):>6}  "
                  f"{g(f'{position.entry_price:.4f}', C.CYN):>10}  "
                  f"{g(f'{position.target_price:.4f}', C.GRN):>10}  "
                  f"{g(f'{position.stop_loss_price:.4f}', C.RED):>10}")

    def print_per_symbol(self, closed_trades: Dict[str, Any]) -> None:
        """Print results per symbol."""
        stats, per_sym = self.compute_stats(closed_trades)
        t = stats["trades_total"]

        if t == 0:
            return

        print(section("", "VYSLEDKY PO MENACH"))
        print(f"    {g('Mena', C.GRY):<5}  "
              f"{g('Obch', C.GRY):>4}  "
              f"{g('WR', C.GRY):>5}  "
              f"{g('Bar', C.GRY):<20}  "
              f"{g('Zisk', C.GRY):>12}")
        print(f"    {g('-' * 50, C.GRY)}")

        for symbol in self.trading_symbols:
            short = symbol.replace("USDT", "")
            ts = per_sym.get(symbol)

            if not ts or ts.count == 0:
                print(f"    {g(short, C.GRY):<5}  {g('-', C.GRY)}")
                continue

            swr = ts.win_rate
            if swr is None:
                swr_s = g("N/A", C.GRY + C.BLD)
                icon = g("-", C.GRY)
            else:
                wcol = C.GRN if swr >= 0.55 else (C.YLW if swr >= 0.45 else C.RED)
                swr_s = g(f"{swr*100:.0f}%", wcol + C.BLD)
                icon = g("OK", C.GRN) if swr >= 0.55 else (g("?", C.YLW) if swr >= 0.45 else g("X", C.RED))

            pcol = C.GRN if ts.total_pnl >= 0 else C.RED

            print(f"    {g(short, C.WHT + C.BLD):<5}  "
                  f"{g(str(ts.count), C.WHT):>4}  "
                  f"{swr_s:>5}  "
                  f"{cbar(swr or 0.0, 1.0, lo=0.45, hi=0.55)}  "
                  f"{g(f'{ts.total_pnl:+.8f}', pcol):>12}  {icon}")

    def print_learning_status(self, closed_trades: Dict[str, Any]) -> None:
        """Print learning status and calibration."""
        stats, _ = self.compute_stats(closed_trades)
        t = stats["trades_total"]
        wins = stats["wins"]
        losses = stats["losses"]
        _decisive = wins + losses

        print(section("", "UCENI – STAV A USPESNOST"))

        # Calibration progress
        if _decisive >= 50:
            cal_label = g("KALIBROVAN  ✓", C.GRN + C.BLD)
            cal_note = g(f"({_decisive} rozhodujících obchodů)", C.GRY)
        else:
            cal_label = g(f"{_decisive} / 50 rozhodujících", C.BLU + C.BLD)
            cal_note = g(f"({50 - _decisive} zbývá)", C.GRY)

        print(f"    {g('Kalibrace', C.GRY)}      "
              f"{cal_label}  "
              f"{blue_bar(_decisive, 50)}  "
              f"{cal_note}")

        # Learning trend
        if t >= 10:
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0.0
            trend_s = "SBÍRÁ DATA..."
            tcol = C.GRY
            print(f"    {g('Trend učení', C.GRY)}    {g(trend_s, tcol + C.BLD)}")
        else:
            print(f"    {g('Trend učení', C.GRY)}    "
                  f"{g(f'Čeká na {10-t} obchodů...', C.GRY)}")

    def print_status(self, closed_trades: Dict[str, Any],
                    entries_attempted: int = 0, entries_successful: int = 0,
                    entries_rejected: int = 0, trades_closed: int = 0,
                    open_positions_count: int = 0, open_notional: float = 0.0,
                    open_positions_dict: Optional[Dict[str, Any]] = None,
                    status_tag: str = "AKTIVNI") -> None:
        """Print complete dashboard status."""
        if open_positions_dict is None:
            open_positions_dict = {}
        self.print_header(status_tag)
        self.print_trading_performance(closed_trades, entries_attempted,
                                       entries_successful, entries_rejected, trades_closed,
                                       open_positions_count, open_notional)
        self.print_open_positions(open_positions_dict)
        self.print_per_symbol(closed_trades)
        self.print_learning_status(closed_trades)
        print(f"\n{g('=' * self.W, C.CYN)}\n")
