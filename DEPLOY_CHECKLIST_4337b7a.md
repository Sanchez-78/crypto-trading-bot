# Deployment Checklist: 4337b7a (Emergency Read Quota Containment)

## Pre-Deployment

**Verify commit is locally committed**:
```bash
git log --oneline -5
# Expect: 4337b7a at top
git status --short
# Expect: clean (only untracked plan files ok)
```

## Deployment Steps

1. **Push to remote** (after approval):
   ```bash
   git push origin main
   ```

2. **Deploy to Hetzner** via GitHub Actions auto-deploy (triggered by push)

3. **Monitor startup** (~2-3 min post-deploy):
   - Check runtime marker in logs:
     ```bash
     tail -100 /var/log/bot.log | grep "runtime_marker\|version"
     # Expect: commit hash 4337b7a or newer
     ```

4. **Verify no startup errors**:
   ```bash
   tail -50 /var/log/bot.log | grep -i "error\|exception"
   grep -E "firebase_client|auto_cleaner" /var/log/bot.log | grep -i "error"
   # Expect: no errors
   ```

## Post-Deployment Quota Monitoring

**T+0 (baseline)**: Record Firebase reads from `get_quota_status()`
```bash
python -c "from src.services.firebase_client import get_quota_status; print(get_quota_status())"
# Record: reads_0
```

**T+15min**: Record reads
```bash
# Record: reads_15
```

**T+60min**: Record reads + compute reads/hour
```bash
# Record: reads_60
# Compute: reads_per_hour = (reads_60 - reads_0) / 1.0
```

**Expected metrics**:
- ✅ reads_per_hour < 600 (vs. 50,000 peak before patch)
- ✅ auto_cleaner logs: max 1x per hour
- ✅ No read quota exceeded alerts

## Success Criteria

- ✅ Deployment completes without errors
- ✅ Runtime marker shows 4337b7a or newer
- ✅ Reads/hour trending toward 30-35k/day (400-500/hour)
- ✅ No Firebase 429 errors in logs

## Rollback (if needed)

```bash
git revert 4337b7a --no-edit
git push origin main
# Auto-deploy via Actions
# Redeploy; monitor for quota recovery
```

---

**Status**: Committed locally. Awaiting approval to push.
