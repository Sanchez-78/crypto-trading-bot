#!/bin/bash
# Daily Health Check — 7-day freeze baseline monitoring
# Run every morning: 0 9 * * * /opt/cryptomaster/scripts/daily_health_check.sh

cd /opt/cryptomaster || exit 1

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOGFILE="/tmp/daily_health_${TIMESTAMP// /_}.log"

{
    echo "╔════════════════════════════════════════════════════════════════════════════════╗"
    echo "║ DAILY HEALTH CHECK — $(date '+%Y-%m-%d')"
    echo "╚════════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    echo "=== 1. CRITICAL ALERTS (Reason to patch immediately) ==="
    echo "Checking: RECON != OK, outbox failed, dashboard zero, quota risk, crashes, missing learning after PAPER_EXIT"
    echo ""

    CRITICAL_ALERT=0

    # Check RECON status
    if journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -q "V10.13x.1 RECON.*status=WARN\|status=FAIL"; then
        echo "🔴 CRITICAL: RECON status != OK"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ RECON status: OK"
    fi

    # Check outbox
    if journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -q "V5_BRIDGE_OUTBOX_FLUSH_FAILED\|outbox.*failed"; then
        echo "🔴 CRITICAL: Outbox has failed events"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ Outbox: No failed events"
    fi

    # Check dashboard metrics
    if journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep "V5_BRIDGE_DASHBOARD_METRICS" | tail -1 | grep -q "closed_today=0.*exits_1h=0.*learning_updates=0"; then
        echo "🔴 CRITICAL: Dashboard metrics all-zero (possible crash)"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ Dashboard: Metrics flowing"
    fi

    # Check Firebase quota
    QUOTA_LINE=$(journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep "V5_BRIDGE_QUOTA_STATE" | tail -1)
    if echo "$QUOTA_LINE" | grep -q "writes.*\(1[5-9][0-9][0-9][0-9]\|[2-9][0-9][0-9][0-9][0-9]\)"; then
        echo "🔴 CRITICAL: Firebase write quota approaching/exceeded limit"
        echo "   $QUOTA_LINE"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ Firebase quota: NORMAL"
    fi

    # Check for crashes
    if journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -q "Traceback\|Exception.*fatal\|FATAL"; then
        echo "🔴 CRITICAL: Traceback / runtime crash detected"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ Service: No crashes"
    fi

    # Check learning updates after PAPER_EXIT
    LEARNING_UPDATES=$(journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -c "PAPER_CANONICAL_LEARNING_UPDATE.*outcome=")
    if [ "$LEARNING_UPDATES" -eq 0 ]; then
        echo "⚠️  WARNING: No learning updates from closed trades"
        CRITICAL_ALERT=$((CRITICAL_ALERT + 1))
    else
        echo "✅ Learning: $LEARNING_UPDATES updates recorded"
    fi

    echo ""
    if [ "$CRITICAL_ALERT" -gt 0 ]; then
        echo "🚨 CRITICAL ALERTS: $CRITICAL_ALERT issue(s) requiring immediate patch!"
        echo ""
    else
        echo "✅ No critical issues — freeze continues"
        echo ""
    fi

    echo "=== 2. BASELINE METRICS (For 7-day analysis) ==="
    echo ""

    # Entry rate (24h)
    ENTRIES_24H=$(journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -c "admission_reason=paper_learning\|PAPER_ENTRY_ADMIT")
    echo "📊 Paper entries (24h): $ENTRIES_24H"

    # Learning updates (24h)
    LEARNING_24H=$(journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -c "V5_BRIDGE_LEARNING_UPDATE")
    echo "📊 Learning updates (24h): $LEARNING_24H"

    # Entry blocking reasons (top 5)
    echo "📊 Top entry block reasons (24h):"
    journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | \
        grep "source_reject=\|reject_reason=" | \
        grep -o "reject_reason=[^ ]*\|source_reject=[^ ]*" | \
        sort | uniq -c | sort -rn | head -5 | awk '{print "   " $2 ": " $1}'

    echo ""

    # Cost-edge diagnostics
    echo "📊 Cost-edge expected vs required move (sample):"
    journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | \
        grep "expected_move_pct=\|required_move_pct=" | tail -3 | \
        grep -o "expected_move_pct=[^ ]*\|required_move_pct=[^ ]*" | paste - - | head -2 | \
        awk '{print "   " $0}'

    echo ""

    # ECON_BAD rejects
    ECON_BAD_REJECTS=$(journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | grep -c "REJECT_ECON_BAD")
    echo "📊 ECON_BAD rejects (24h): $ECON_BAD_REJECTS"

    # Learning segment performance (top/worst)
    echo "📊 Learning segment performance (sample):"
    journalctl -u cryptomaster.service --since "24 hours ago" --no-pager 2>/dev/null | \
        grep "rolling.*_pf=" | tail -5 | \
        grep -o "segment=[^ ]*\|_pf=[^ ]*" | paste - - | head -3 | \
        awk '{print "   " $1 " " $2}'

    echo ""

    # Service health
    echo "=== 3. SERVICE STATUS ==="
    systemctl status cryptomaster.service --no-pager -l | sed -n '1,10p'

    echo ""

    # Outbox status
    echo "=== 4. OUTBOX STATUS ==="
    if [ -f venv/bin/python ] && [ -f scripts/audit_v5_outbox.py ]; then
        venv/bin/python scripts/audit_v5_outbox.py 2>/dev/null | head -20
    else
        echo "⚠️  Audit script not available"
    fi

    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════════════╗"
    echo "║ END OF DAILY CHECK — Next: Tomorrow 9:00 UTC"
    echo "╚════════════════════════════════════════════════════════════════════════════════╝"

} | tee "$LOGFILE"

# Keep last 7 daily logs
find /tmp/daily_health_*.log -mtime +7 -delete 2>/dev/null || true

echo ""
echo "Log saved: $LOGFILE"
