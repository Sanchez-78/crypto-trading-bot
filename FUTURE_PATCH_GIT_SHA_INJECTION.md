# Future Patch Plan: Git SHA Injection for Runtime Marker (Unimplemented)

**Status**: Design only. Do not implement yet.  
**Priority**: Low (cosmetic/observability)  
**Trigger**: After Phase 1 emergency monitoring complete

---

## Problem

Deployed bot shows runtime marker with commit UNKNOWN instead of actual commit hash.

**Root cause**: `.git` directory unavailable on Hetzner server (expected in Docker/CI deployments).

**Current behavior**:
```
runtime_marker: {commit: 'UNKNOWN', branch: 'UNKNOWN', host: 'bot-prod', ...}
```

**Desired behavior**:
```
runtime_marker: {commit: '4337b7a', branch: 'main', host: 'bot-prod', ...}
```

---

## Solution: Git SHA Injection via GitHub Actions

**Mechanism**:
1. GitHub Actions captures git commit hash at build time
2. Passes commit hash as environment variable to Docker build
3. `version_info.py` reads env var and caches value at startup
4. Fallback to .git if available; use env var if not

**Implementation files**:
- `.github/workflows/deploy.yml` — add `COMMIT_SHA` env var export
- `src/services/version_info.py` — add env var fallback to `get_git_commit()`
- `bot2/main.py` — no changes (uses version_info as-is)

**Pseudocode**:

```python
# src/services/version_info.py

def get_git_commit() -> str:
    """Get commit hash from .git or GitHub Actions env var."""
    # Try env var first (CI deployment)
    commit_env = os.getenv("COMMIT_SHA", "")
    if commit_env and len(commit_env) >= 7:
        return commit_env[:7]  # 7-char short form
    
    # Fallback: try .git
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    
    return "UNKNOWN"
```

**GitHub Actions workflow change**:
```yaml
# .github/workflows/deploy.yml

env:
  COMMIT_SHA: ${{ github.sha }}

jobs:
  deploy:
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker image
        run: docker build --build-arg COMMIT_SHA=${{ github.sha }} -t bot:latest .
```

---

## Expected Effect

- ✅ Runtime marker shows actual commit hash on Hetzner
- ✅ Logs include deployment version for troubleshooting
- ✅ No behavior change (observability only)

---

## Implementation Notes

- **Timing**: After Phase 1 monitoring window (post-quota-reset)
- **Scope**: ~15 lines (env var check + fallback)
- **Risk**: Very low (reads env var, falls back to existing logic)
- **Testing**: Deploy to Hetzner; verify logs show commit hash

---

**Status**: Planned. Awaiting post-Phase-1 review for implementation.
