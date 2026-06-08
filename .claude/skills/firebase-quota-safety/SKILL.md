---
name: firebase-quota-safety
description: |
  Validates Firebase quota compliance: zero per-tick operations, quota caps 
  honored, batching working, cache effective, outbox safe, fail-closed modes 
  tested. Run when touching Firebase code or after heavy trading sessions.

---

# Firebase Quota Safety Skill

## Quota Audit

### Daily Limits
- **Reads:** 50,000/day (reset 07:00 UTC)
- **Writes:** 20,000/day (reset 07:00 UTC)

### Check Current Usage
```bash
python3 -c "from src.services.firebase_client import get_quota_status; print(get_quota_status())"
```

Expected:
```
{'reads_used': 380, 'reads_limit': 50000, 'writes_used': 145, 'writes_limit': 20000}
```

### Per-Tick Rate Check
```bash
journalctl -u cryptomaster --since "10 minutes ago" | grep -E "Firebase|firebase" | wc -l
# Should be < 100 lines for 10 min (< 0.15/sec)
```

## Batch Validation

**All writes must use `save_batch()`:**
```bash
grep -n "set\|update" src/services/*.py | grep -v "save_batch\|_POSITIONS\|config"
```

Should be 0 matches (outside of collections).

## Cache Effectiveness

**Memory cache hit rate:**
```bash
grep "\[CACHE_HIT\]" logs/app.log | wc -l   # Should be high
grep "\[CACHE_MISS\]" logs/app.log | wc -l  # Should be low
```

Ratio: >=80% hits = good.

## Fail-Closed Test

Simulate quota exhausted:

```python
# In firebase_client.py
_quota_state = {
    'reads_used': 50000,
    'writes_used': 20000,
}

# Try to trade
# Expected: Bot continues, uses cache, queues writes in outbox
```

Verify:
- ✅ Bot doesn't crash
- ✅ Logs show quota exhaustion warning
- ✅ Uses cache for reads
- ✅ Outbox catches writes

## Gates

- ✅ PASS: Usage <30% of limits AND cache >80% hit AND per-tick safe
- ⚠️ CAUTION: Usage 30-50% OR cache 60-80%
- ❌ FAIL: Usage >50% OR cache <60% OR per-tick violations found
