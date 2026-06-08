---
name: deployment-readiness-review
description: |
  Final deployment readiness gate. Confirms all agents approved, all gates 
  passed, tests passing, safety verified. Signs off on ready-to-deploy patches.

---

# Deployment Readiness Review Skill

## Final Checklist

### All Agent Reviews Complete?

- [ ] runtime-forensic-agent: ✓ Investigation complete, evidence gathered
- [ ] paper-learning-agent: ✓ Learning validation passed (if applicable)
- [ ] firebase-quota-agent: ✓ Quota safe, no new operations
- [ ] trading-safety-agent: ✓ No real trading paths exposed
- [ ] test-regression-agent: ✓ All tests pass, no new failures
- [ ] android-contract-agent: ✓ Dashboard contract maintained (if UI touched)
- [ ] patch-author-agent: ✓ Minimal patch created
- [ ] reviewer-agent: ✓ Independent approval obtained

### Deployment Safety

- [ ] Code review passed (all agents approved)
- [ ] Tests passing (regression suite clean)
- [ ] No state contamination detected
- [ ] Firebase quota headroom >20%
- [ ] No real trading paths touched
- [ ] Dashboard metrics correct (if applicable)
- [ ] Android contract compliant (if UI touched)

### Deploy Type

**PAPER_LIVE deploy (auto-deploy to Hetzner):**
- ✅ Ready to push to main
- Auto-deploy triggers on GitHub Actions
- No manual approval needed

**REAL_LIVE deploy (if applicable):**
- ❌ **BLOCKED for this harness**
- Requires CEO/CTO authorization
- Separate instance, separate config
- Manual deployment process

## Deployment Commands

```bash
# For PAPER_LIVE:
git push origin main
# → GitHub Actions auto-deploys to /opt/cryptomaster

# For REAL_LIVE (rare, blocked unless authorized):
# Contact CEO/CTO for explicit approval
```

## Post-Deploy Monitoring (30 min)

After deploy:
1. Check service is running
2. Monitor logs for errors
3. Verify metrics dashboard updates
4. Check for new edge cases

## Sign-Off

**Ready for deployment: ✅ YES | ⚠️ CAUTION | ❌ NOT READY**

Status: [Choose one]
