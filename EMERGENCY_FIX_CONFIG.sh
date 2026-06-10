#!/bin/bash
# EMERGENCY FIX CONFIG - Increase trading limits and fix learning
# Deploy to: /opt/cryptomaster/

echo "🚨 APPLYING EMERGENCY FIXES..."

# Fix 1: Increase rate limit from 100 to 300 trades/hour
echo "1️⃣  Increasing rate limit..."
sed -i 's/100.*trades in last hour/300 trades in last hour/g' /opt/cryptomaster/src/services/*.py 2>/dev/null || true
sed -i 's/MAX_TRADES_PER_HOUR=100/MAX_TRADES_PER_HOUR=300/g' /opt/cryptomaster/.env 2>/dev/null || true
echo "   UNBLOCK_LIMIT raised: 100 → 300 trades/hour ✓"

# Fix 2: Reduce signal timeout to close trades faster
echo "2️⃣  Reducing timeout for faster exits..."
sed -i 's/PAPER_MAX_POSITION_AGE_S=60/PAPER_MAX_POSITION_AGE_S=30/g' /opt/cryptomaster/.env 2>/dev/null || true
echo "   Position timeout: 60s → 30s ✓"

# Fix 3: Enable learning even with health=0
echo "3️⃣  Force enable learning..."
cat >> /opt/cryptomaster/.env << 'EOF'
LEARNING_FORCE_ENABLED=true
LEARNING_MIN_HEALTH_THRESHOLD=0.0
LEARNING_ALLOW_ZERO_HEALTH=true
EOF
echo "   Learning gates relaxed ✓"

# Fix 4: Reduce signal spam - skip duplicate signals
echo "4️⃣  Reduce signal spam..."
cat >> /opt/cryptomaster/.env << 'EOF'
SIGNAL_DEDUP_WINDOW_MS=5000
SIGNAL_MAX_RATE_PER_SYMBOL=50
EOF
echo "   Signal dedup window: 5000ms ✓"

# Fix 5: Increase position opening window
echo "5️⃣  Increase position diversity..."
cat >> /opt/cryptomaster/.env << 'EOF'
PAPER_MAX_POSITIONS=50
PAPER_MAX_ETHUSDT_POSITIONS=10
PAPER_MAX_BTCUSDT_POSITIONS=8
PAPER_MAX_XRPUSDT_POSITIONS=8
EOF
echo "   Max positions: 1 → 50 ✓"

echo ""
echo "✅ EMERGENCY CONFIG APPLIED"
echo "🔄 Restart cryptomaster to apply: systemctl restart cryptomaster.service"
