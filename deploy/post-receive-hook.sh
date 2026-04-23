#!/bin/bash
# POST-RECEIVE HOOK for auto-deployment
# Install on Hetzner server at: /opt/cryptomaster/.git/hooks/post-receive
# Make executable: chmod +x /opt/cryptomaster/.git/hooks/post-receive

set -e

PROJECT_DIR="/opt/cryptomaster"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/deploy.log"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
TRADING_LOG="$LOG_DIR/trading.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

{
    echo "=========================================="
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] AUTO-DEPLOY TRIGGERED"
    echo "=========================================="

    # Navigate to project
    cd "$PROJECT_DIR"

    # Read the ref being pushed (should be main)
    read oldrev newrev refname

    echo "Ref: $refname (old: $oldrev new: $newrev)"

    # Only deploy on main branch
    if [ "$refname" = "refs/heads/main" ]; then
        echo "✓ Deploying main branch..."

        # Update working directory
        git --work-tree="$PROJECT_DIR" --git-dir="$PROJECT_DIR/.git" checkout -f main

        echo "✓ Code updated"

        # Kill old bot process
        echo "Stopping old bot process..."
        pkill -f "python.*start.py" || true
        sleep 2

        echo "✓ Old process stopped"

        # Optional: Reset database (removes stale Firebase data)
        echo "Resetting database..."
        $VENV_PYTHON -m src.services.reset_db 2>/dev/null || true
        sleep 1

        echo "✓ Database reset"

        # Start new bot
        echo "Starting new bot..."
        nohup $VENV_PYTHON start.py > "$TRADING_LOG" 2>&1 &
        BOT_PID=$!

        echo "✓ Bot started (PID: $BOT_PID)"

        # Wait a moment and verify it's running
        sleep 3
        if ps -p $BOT_PID > /dev/null; then
            echo "✓ Bot verification: RUNNING"
        else
            echo "✗ Bot verification: FAILED"
            tail -20 "$TRADING_LOG"
            exit 1
        fi

        echo "=========================================="
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] DEPLOYMENT COMPLETE"
        echo "=========================================="
    else
        echo "⊘ Not main branch, skipping deployment"
    fi

} >> "$LOG_FILE" 2>&1
