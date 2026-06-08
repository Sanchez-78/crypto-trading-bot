---
name: android-dashboard-contract
description: |
  Validates Czech Android dashboard API contract. Verifies JSON shape matches 
  schema, field types correct, all labels in Czech, timestamps ISO8601 UTC. 
  Ensures API returns what Android app expects.

---

# Android Dashboard Contract Skill

## Contract Validation

### Step 1: Fetch Metrics

```bash
curl http://localhost:8080/metrics -s | jq . > api_response.json
```

### Step 2: Validate Schema

**Expected fields (from Android contract):**
```json
{
  "open_positions": [
    {"trade_id", "symbol", "side", "entry_price", "current_price", 
     "tp", "sl", "pnl_pct", "hold_s", "age_s"}
  ],
  "closed_today": number,
  "total_trades": number,
  "win_rate_pct": number,
  "profit_factor": number,
  "learning_status": "UČENÍ|PŘIPRAVEN|VYPNUTO",
  "recommendation": "KOUPIT|PRODAT|ČEKAT|POČKAT",
  "last_update_utc": "ISO8601Z"
}
```

**Check:**
```bash
jq 'keys' api_response.json  # All keys present?
jq '.open_positions[0] | keys' api_response.json  # Position schema correct?
jq '.learning_status' api_response.json  # Czech value or English?
```

### Step 3: Localization (Czech)

```bash
jq '.learning_status' api_response.json
# ✅ "UČENÍ" (Learning)
# ❌ "LEARNING"

jq '.recommendation' api_response.json
# ✅ "KOUPIT" (Buy)
# ❌ "BUY"
```

**All user-facing strings must be Czech.**

### Step 4: Timestamp Validation

```bash
jq '.last_update_utc' api_response.json
# ✅ "2026-06-08T10:15:30.123Z"
# ❌ "2026-06-08 10:15:30" (missing Z, milliseconds)
```

**Requirements:**
- ISO8601 format
- Z suffix for UTC
- Millisecond precision

### Step 5: Value Consistency

```bash
# Get API values
CLOSED=$(jq '.closed_today' api_response.json)

# Get DB values
sqlite3 learning.db "SELECT COUNT(*) FROM trades WHERE close_ts >= strftime('%s', 'now', 'start of day');"

# Compare
[ "$CLOSED" = "$DB_COUNT" ] && echo "✅ Match" || echo "❌ Mismatch"
```

## Gates

- ✅ PASS: All fields present + correct types + all Czech + timestamps ISO8601 UTC
- ❌ FAIL: Missing fields, wrong types, English labels, or malformed timestamps
