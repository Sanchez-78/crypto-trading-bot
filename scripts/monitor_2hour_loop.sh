#!/bin/bash
# 2-hour monitoring loop — collect metrics every 5 minutes

TARGET_DURATION=7200  # 2 hours in seconds
CHECK_INTERVAL=300    # Check every 5 minutes
START_TIME=$(date +%s)

HETZNER_KEY="$HOME/.ssh/hetzner_root"
HETZNER_HOST="root@78.47.2.198"
HETZNER_CMD="cd /opt/cryptomaster && python3 scripts/audit_v5_outbox.py 2>&1 && journalctl -u cryptomaster.service --since '6 minutes ago' --no-pager 2>&1 | tail -80"

echo "═══════════════════════════════════════════════════════════"
echo "2-HOUR MONITORING LOOP — Starting $(date)"
echo "═══════════════════════════════════════════════════════════"

while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    REMAINING=$((TARGET_DURATION - ELAPSED))

    if [ $REMAINING -le 0 ]; then
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo "✅ 2-HOUR MONITORING COMPLETE"
        echo "Total elapsed: $(($ELAPSED / 60)) minutes"
        echo "═══════════════════════════════════════════════════════════"
        break
    fi

    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo "CHECKPOINT $(date '+%H:%M:%S UTC') — $(($REMAINING / 60))m remaining"
    echo "────────────────────────────────────────────────────────────"

    # Fetch remote metrics
    ssh -i "$HETZNER_KEY" "$HETZNER_HOST" "$HETZNER_CMD" 2>&1 | tail -60

    sleep $CHECK_INTERVAL
done
