#!/bin/bash
# CYCLE #13 FINAL MEASUREMENT SCRIPT
# Run this on Hetzner to collect metrics from 06:56-07:26 UTC window
# Usage: ssh root@78.47.2.198 'bash /opt/cryptomaster/cycle13_measure.sh'

set -e

echo "==============================================="
echo "CYCLE #13 FINAL MEASUREMENT"
echo "Window: 2026-06-16 06:56-07:26 UTC"
echo "==============================================="
echo ""

# 1. EXIT DISTRIBUTION
echo "[1] EXIT DISTRIBUTION:"
echo "Counting exit reasons..."
EXITS=$(journalctl -u cryptomaster.service --since "06:56" --until "07:26" --no-pager 2>/dev/null | \
  grep "PAPER_EXIT" | \
  awk -F'exit_reason=' '{print $2}' | awk '{print $1}' | sort | uniq -c)

TP_COUNT=$(echo "$EXITS" | grep -oP '^\s+\d+\s+TP$' | awk '{print $1}' || echo "0")
SL_COUNT=$(echo "$EXITS" | grep -oP '^\s+\d+\s+SL$' | awk '{print $1}' || echo "0")
TIMEOUT_COUNT=$(echo "$EXITS" | grep -oP '^\s+\d+\s+TIMEOUT$' | awk '{print $1}' || echo "0")
TOTAL=$((TP_COUNT + SL_COUNT + TIMEOUT_COUNT))

if [ $TOTAL -eq 0 ]; then
  echo "  ERROR: No PAPER_EXIT logs found in window!"
  TOTAL=1
fi

TP_PCT=$((TP_COUNT * 100 / TOTAL))
SL_PCT=$((SL_COUNT * 100 / TOTAL))
TIMEOUT_PCT=$((TIMEOUT_COUNT * 100 / TOTAL))

echo "  Total exits: $TOTAL"
echo "  TP: $TP_COUNT ($TP_PCT%)"
echo "  SL: $SL_COUNT ($SL_PCT%)"
echo "  TIMEOUT: $TIMEOUT_COUNT ($TIMEOUT_PCT%)"
echo ""

# 2. HOLD TIME VERIFICATION
echo "[2] HOLD TIME VERIFICATION (Proof of config fix):"
HOLD_TIMES=$(journalctl -u cryptomaster.service --since "06:56" --until "07:26" --no-pager 2>/dev/null | \
  grep "PAPER_EXIT" | \
  grep -oP 'hold_s=\K[0-9]+' || echo "")

if [ -z "$HOLD_TIMES" ]; then
  echo "  ERROR: No hold_s values found!"
  AVG_HOLD="unknown"
else
  AVG_HOLD=$(echo "$HOLD_TIMES" | awk '{s+=$1; n++} END {print int(s/n)}')
  MAX_HOLD=$(echo "$HOLD_TIMES" | sort -n | tail -1)
  MIN_HOLD=$(echo "$HOLD_TIMES" | sort -n | head -1)
  echo "  Average hold_s: ${AVG_HOLD}s"
  echo "  Min: ${MIN_HOLD}s, Max: ${MAX_HOLD}s"
  if [ "$MAX_HOLD" -lt 600 ]; then
    echo "  ✅ CONFIG PROOF: max_hold < 600s (fix applied!)"
  elif [ "$MAX_HOLD" -eq 900 ]; then
    echo "  ❌ CONFIG FAILURE: max_hold = 900s (still old!)"
  fi
fi
echo ""

# 3. WIN RATE FROM LOGS
echo "[3] TRADE QUALITY (Win Rate):"
WR_DATA=$(journalctl -u cryptomaster.service --since "06:56" --until "07:26" --no-pager 2>/dev/null | \
  grep "PAPER_EXIT" | \
  grep -oP 'net_pnl_pct=\K[-0-9.]+' | \
  awk '{wins += ($1 > 0.001); losses += ($1 < -0.001); total++} END {if (total>0) print "wins="wins" losses="losses" total="total" wr="int(wins*100/total)}' || echo "no_data")

echo "  $WR_DATA"
echo ""

# 4. LEARNING DB CHECK
echo "[4] LEARNING DATABASE (SQLite verification):"
if [ -f "/opt/cryptomaster/local_learning_storage/learning_database.sqlite" ]; then
  DB_STATS=$(sqlite3 /opt/cryptomaster/local_learning_storage/learning_database.sqlite \
    "SELECT COUNT(*) as total, \
            COUNT(CASE WHEN exit_reason='TP' THEN 1 END) as tp, \
            COUNT(CASE WHEN exit_reason='SL' THEN 1 END) as sl, \
            COUNT(CASE WHEN exit_reason='TIMEOUT' THEN 1 END) as timeout \
     FROM trades;" 2>/dev/null || echo "error")
  echo "  $DB_STATS"
else
  echo "  Database file not found!"
fi
echo ""

# 5. SERVICE STATUS
echo "[5] SERVICE STATUS:"
systemctl status cryptomaster.service --no-pager 2>/dev/null | head -5
echo ""

# 6. ENVIRONMENT CHECK
echo "[6] ENVIRONMENT VERIFICATION:"
PID=$(pgrep -f "python3 start.py" 2>/dev/null || echo "unknown")
if [ "$PID" != "unknown" ]; then
  PAPER_MAX=$(cat /proc/$PID/environ 2>/dev/null | tr '\0' '\n' | grep "PAPER_MAX_POSITION_AGE_S" || echo "NOT_FOUND")
  echo "  Running PID: $PID"
  echo "  $PAPER_MAX"
else
  echo "  ERROR: python3 process not found!"
fi
echo ""

echo "==============================================="
echo "CYCLE #13 MEASUREMENT COMPLETE"
echo "==============================================="
