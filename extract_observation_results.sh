#!/bin/bash
# Extract observation session results from report JSON

extract_session() {
    local dir="$1"
    local session_name="$2"

    if [ ! -d "$dir" ]; then
        echo "[$session_name] Directory not found: $dir"
        return 1
    fi

    local report=$(find "$dir" -name "report_*.json" -type f | head -1)
    if [ ! -f "$report" ]; then
        echo "[$session_name] Report not found in $dir"
        return 1
    fi

    echo "=== $session_name Results ==="
    echo "Directory: $dir"
    echo ""

    # Extract metrics from JSON
    python3 << 'PYTHON'
import json
import sys

with open("'"$report"'") as f:
    data = json.load(f)

meta = data.get("live_session_metadata", {})

print(f"Duration (actual): {meta.get('last_market_event_at', 'N/A')}s")
print(f"bookTicker events: {meta.get('book_ticker_events', 0)}")
print(f"aggTrade events: {meta.get('agg_trade_events', 0)}")
print(f"Reconnects: {meta.get('feed_reconnect_count', 0)}")
print(f"Timeouts: {meta.get('feed_timeout_count', 0)}")
print(f"Closed trades: {data.get('closed_trades_count', 0)}")
print("")

if data.get('closed_outcomes'):
    for i, outcome in enumerate(data['closed_outcomes'], 1):
        print(f"Trade {i}:")
        print(f"  Entry: {outcome.get('entry_price')}")
        print(f"  Exit: {outcome.get('exit_price')}")
        print(f"  Gross PnL: {outcome.get('gross_pnl_pct')}%")
        print(f"  Fees: {outcome.get('fee_cost_pct')}%")
        print(f"  Net PnL: {outcome.get('net_pnl_pct')}%")
        print(f"  Metrics eligible: {outcome.get('eligible_for_clean_paper_metrics')}")
        print(f"  Readiness eligible: {outcome.get('eligible_for_real_readiness')}")
else:
    print("No closed trades in this session")
PYTHON

    echo ""
}

# Usage
extract_session "$1" "$2"
