# Firebase Quota Monitoring: Post 4337b7a Deployment

**Commit**: 4337b7a (Emergency: contain Firebase read quota usage)  
**Deployed**: 2026-04-25  
**Deployment Status**: ✅ Active

## Deployment Verification Results

| Check | Result | Notes |
|-------|--------|-------|
| App startup | ✅ Success | Running normally |
| Cache TTL patch | ✅ Active | WEIGHTS_TTL=7200s confirmed |
| Runtime marker | ⚠️ UNKNOWN | .git unavailable on server (future fix needed) |
| Quota status | ⚠️ Exhausted | Measurement deferred to post-reset |

## Baseline Reading (T+0)

**Record when quota resets (midnight Pacific = 09:00 GMT+2)**:
```bash
python -c "from src.services.firebase_client import get_quota_status; import json; print(json.dumps(get_quota_status(), indent=2))"
```

**T+0 Reads**: [TO BE RECORDED AFTER RESET]

## Monitoring Schedule (Post-Reset)

| Time | Action | Reads Value | Notes |
|------|--------|-------------|-------|
| T+0 | Record baseline | — | At quota reset (09:00 GMT+2) |
| T+15 | Record reads | — | 15 minutes after reset |
| T+60 | Record reads + compute | — | 60 minutes after reset; calc reads/hour |

## Expected Post-Patch Metrics

| Metric | Target | Threshold |
|--------|--------|-----------|
| reads_per_hour | 400-500 | < 700 (safe) |
| auto_cleaner frequency | 1x/hour max | No errors |
| 429 errors | 0 | None acceptable |
| Cache hit rate | Higher (2h TTLs) | Observable reduction in reads |

## Quota Reset Timeline

- **Reset time**: Midnight Pacific Time = 09:00 GMT+2 = 07:00 UTC
- **Next reset**: 2026-04-26 09:00 GMT+2
- **Post-reset window**: Monitor continuously for 60+ minutes

## Future Improvement: Git SHA Injection

**Issue**: Runtime marker shows UNKNOWN (no .git on server)  
**Solution**: Inject git SHA from GitHub Actions build environment into deployment  
**Implementation**: Future patch (do not implement yet)  
**Files affected**: bot2/main.py, src/services/version_info.py  
**Mechanism**: GitHub Actions env var → Docker build → deployed binary includes commit hash

---

**Status**: Baseline recorded. Awaiting quota reset for post-patch measurement.
