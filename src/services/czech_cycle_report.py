"""
Czech Cycle Report — Periodic status dump of trading & learning state

Po každém cyklu robota: otevřené obchody, zavřené obchody, učení, metrika, quota.
"""

import json
import sys
from typing import Any, Dict, Optional
from datetime import datetime

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


class CzechCycleReporter:
    """Generuj kompletní český report stavu."""

    def __init__(self):
        pass

    def generate_cycle_report(
        self,
        open_positions: Dict[str, Any],
        closed_today: list,
        learning_stats: Dict[str, Any],
        trading_stats: Dict[str, Any],
        quota_state: Dict[str, Any],
        v5_bridge_status: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generuj kompletní český report cyklu.

        Args:
            open_positions: Slovník otevřených pozic {trade_id: position_data}
            closed_today: Seznam zavřených obchodů dnes
            learning_stats: LM stats (obchody, spolehlivost, atribuce)
            trading_stats: Počty vstupů/výstupů
            quota_state: Quota usage (reads/writes)
            v5_bridge_status: V5 bridge status (optional)

        Returns:
            Multiline Czech report string
        """
        report = []
        report.append("")
        report.append("=" * 80)
        report.append(f"CYKLUS STAVU — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 80)

        # 1. Otevřené obchody
        report.extend(self._section_open_positions(open_positions))

        # 2. Zavřené obchody
        report.extend(self._section_closed_today(closed_today))

        # 3. Učení
        report.extend(self._section_learning(learning_stats))

        # 4. Metriky obchodování
        report.extend(self._section_trading_metrics(trading_stats))

        # 5. Quota
        report.extend(self._section_quota(quota_state))

        # 6. V5 Bridge (pokud dostupný)
        if v5_bridge_status:
            report.extend(self._section_v5_bridge(v5_bridge_status))

        report.append("=" * 80)
        report.append("")

        return "\n".join(report)

    def _section_open_positions(self, open_positions: Dict[str, Any]) -> list:
        """Sekce: Otevřené obchody."""
        lines = []
        count = len(open_positions)
        lines.append("")
        lines.append("📂 OTEVŘENÉ OBCHODY")
        lines.append("-" * 80)

        if count == 0:
            lines.append("  Žádné otevřené obchody")
        else:
            lines.append(f"  Celkem: {count}")
            for trade_id, pos in list(open_positions.items())[:10]:  # Max 10
                symbol = pos.get("symbol", "N/A")
                side = pos.get("side", "N/A")
                entry = pos.get("entry_price", 0)
                size = pos.get("size_usd", 0)
                duration = pos.get("duration_seconds", 0)
                lines.append(
                    f"    • {symbol:10} {side:4} @{entry:>10.2f} ${size:>8.0f} "
                    f"({duration:>4}s)"
                )

        return lines

    def _section_closed_today(self, closed_today: list) -> list:
        """Sekce: Zavřené obchody."""
        lines = []
        count = len(closed_today)
        lines.append("")
        lines.append("✓ ZAVŘENÉ OBCHODY (dnes)")
        lines.append("-" * 80)

        if count == 0:
            lines.append("  Žádné zavřené obchody")
        else:
            lines.append(f"  Celkem: {count}")

            # Skupiny podle výsledku
            wins = [t for t in closed_today if t.get("net_pnl_pct", 0) > 0]
            losses = [t for t in closed_today if t.get("net_pnl_pct", 0) < 0]
            breakeven = [t for t in closed_today if t.get("net_pnl_pct", 0) == 0]

            if wins:
                lines.append(f"  🟢 ZISKY: {len(wins)}")
                for t in wins[:3]:
                    symbol = t.get("symbol", "N/A")
                    pnl = t.get("net_pnl_pct", 0)
                    reason = t.get("exit_reason", "?")
                    lines.append(f"      {symbol:10} +{pnl:>6.2f}% [{reason}]")

            if losses:
                lines.append(f"  🔴 ZTRÁTY: {len(losses)}")
                for t in losses[:3]:
                    symbol = t.get("symbol", "N/A")
                    pnl = t.get("net_pnl_pct", 0)
                    reason = t.get("exit_reason", "?")
                    lines.append(f"      {symbol:10} {pnl:>6.2f}% [{reason}]")

            if breakeven:
                lines.append(f"  ⚪ BREAK-EVEN: {len(breakeven)}")

        return lines

    def _section_learning(self, learning_stats: Dict[str, Any]) -> list:
        """Sekce: Učení (LM stav)."""
        lines = []
        lines.append("")
        lines.append("📚 UČENÍ (Learning Monitor)")
        lines.append("-" * 80)

        trades_in_lm = learning_stats.get("trades_in_lm", 0)
        calibration_confidence = learning_stats.get("calibration_confidence", 0)
        dominant_attribution = learning_stats.get("dominant_attribution", "N/A")
        attribution_pct = learning_stats.get("attribution_pct", 0)
        update_count = learning_stats.get("update_count", 0)

        lines.append(f"  Obchody v LM:          {trades_in_lm}")
        lines.append(f"  Spolehlivost kalibrace: {calibration_confidence:.1f}%")
        lines.append(f"  Dominantní atribuce:   {dominant_attribution} ({attribution_pct:.1f}%)")
        lines.append(f"  Počet aktualizací:     {update_count}")

        return lines

    def _section_trading_metrics(self, trading_stats: Dict[str, Any]) -> list:
        """Sekce: Metriky obchodování."""
        lines = []
        lines.append("")
        lines.append("📊 METRIKY OBCHODOVÁNÍ")
        lines.append("-" * 80)

        open_count = trading_stats.get("open_positions", 0)
        closed = trading_stats.get("closed_today", 0)
        entries_attempted = trading_stats.get("entries_attempted", 0)
        entries_accepted = trading_stats.get("entries_accepted", 0)
        entries_rejected = trading_stats.get("entries_rejected", 0)
        cost_edge_pass = trading_stats.get("cost_edge_pass", 0)
        cost_edge_fail = trading_stats.get("cost_edge_fail", 0)

        lines.append(f"  Otevřené pozice:        {open_count}")
        lines.append(f"  Zavřené obchody (dnes): {closed}")
        lines.append(f"  Vstupní pokusy:         {entries_attempted}")
        lines.append(f"  Vstupů přijato:         {entries_accepted}")
        lines.append(f"  Vstupů odmítnuto:       {entries_rejected}")
        lines.append(f"  Cost edge PASS:         {cost_edge_pass}")
        lines.append(f"  Cost edge FAIL:         {cost_edge_fail}")

        if entries_accepted > 0:
            acceptance_rate = (entries_accepted / entries_attempted * 100) if entries_attempted > 0 else 0
            lines.append(f"  Přijímací poměr:        {acceptance_rate:.1f}%")

        return lines

    def _section_quota(self, quota_state: Dict[str, Any]) -> list:
        """Sekce: Firebase quota."""
        lines = []
        lines.append("")
        lines.append("⚡ FIREBASE QUOTA")
        lines.append("-" * 80)

        reads = quota_state.get("reads", 0)
        reads_limit = quota_state.get("reads_limit", 20000)
        writes = quota_state.get("writes", 0)
        writes_limit = quota_state.get("writes_limit", 10000)
        quota_state_name = quota_state.get("state", "unknown")

        reads_pct = (reads / reads_limit * 100) if reads_limit > 0 else 0
        writes_pct = (writes / writes_limit * 100) if writes_limit > 0 else 0

        lines.append(f"  Čtení:   {reads:>6}/{reads_limit:<6} ({reads_pct:>5.1f}%)")
        lines.append(f"  Zápisy:  {writes:>6}/{writes_limit:<6} ({writes_pct:>5.1f}%)")
        lines.append(f"  Stav:    {quota_state_name}")

        return lines

    def _section_v5_bridge(self, v5_status: Dict[str, Any]) -> list:
        """Sekce: V5 Legacy Bridge status."""
        lines = []
        lines.append("")
        lines.append("🌉 V5 LEGACY BRIDGE")
        lines.append("-" * 80)

        enabled = v5_status.get("enabled", False)
        component_status = v5_status.get("components", {})
        outbox_pending = v5_status.get("outbox_pending", 0)

        lines.append(f"  Enabled:         {enabled}")

        if component_status:
            for name, status in component_status.items():
                lines.append(f"  {name:>15}    {status}")

        lines.append(f"  Outbox pending:  {outbox_pending} events")

        return lines
