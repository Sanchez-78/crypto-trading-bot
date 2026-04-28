#!/bin/bash

# CryptoMaster V10.13u+20 — P0.3 Production Deployment Verification Script
# Usage: bash scripts/verify_p0_3_deployment.sh

set -e

echo "════════════════════════════════════════════════════════════════"
echo "  CryptoMaster V10.13u+20 — P0.3 Deployment Verification"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Check code changes
echo "[1/6] Checking for P0.3 code changes..."
if grep -q "PAPER_ROUTED\|_save_paper_trade_closed" src/services/trade_executor.py; then
    echo "  ✅ P0.3 integration found in trade_executor.py"
else
    echo "  ❌ P0.3 integration NOT found in trade_executor.py"
    exit 1
fi

# Step 2: Compile check
echo ""
echo "[2/6] Checking code compilation..."
python -m py_compile src/core/runtime_mode.py src/services/paper_trade_executor.py src/services/trade_executor.py bot2/main.py 2>&1 && echo "  ✅ All files compile successfully" || echo "  ❌ Compilation failed"

# Step 3: Run tests
echo ""
echo "[3/6] Running P0 tests..."
if python -m pytest tests/test_paper_mode.py tests/test_p0_3_paper_integration.py -q 2>&1 | tail -1 | grep -q "23 passed"; then
    echo "  ✅ All 23 tests passing"
else
    echo "  ❌ Tests failed or incomplete"
    python -m pytest tests/test_paper_mode.py tests/test_p0_3_paper_integration.py -v
    exit 1
fi

# Step 4: Check runtime mode
echo ""
echo "[4/6] Checking runtime mode functions..."
python -c "
from src.core.runtime_mode import is_paper_mode, live_trading_allowed, get_trading_mode, log_runtime_config
print('  ✅ runtime_mode functions available')
" || echo "  ❌ runtime_mode functions not accessible"

# Step 5: Check paper executor
echo ""
echo "[5/6] Checking paper executor API..."
python -c "
from src.services.paper_trade_executor import open_paper_position, update_paper_positions, close_paper_position
print('  ✅ paper_trade_executor API available')
" || echo "  ❌ paper_trade_executor not accessible"

# Step 6: Check deployment files
echo ""
echo "[6/6] Checking deployment configuration..."
if grep -q "TRADING_MODE=paper_live" .env.example && \
   grep -q "ENABLE_REAL_ORDERS=false" .env.example && \
   grep -q "LIVE_TRADING_CONFIRMED=false" .env.example; then
    echo "  ✅ Safe defaults in .env.example"
else
    echo "  ❌ Safe defaults missing in .env.example"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ P0.3 PRE-DEPLOYMENT VERIFICATION COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. git add src tests .env.example bot2/main.py"
echo "  2. git commit -m 'P0.3: Integrate paper executor into production'"
echo "  3. git push origin main"
echo "  4. sudo systemctl restart cryptomaster"
echo "  5. Wait 30 sec, then verify logs:"
echo "     sudo journalctl -u cryptomaster -n 100 | grep TRADING_MODE"
echo ""
