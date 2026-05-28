# V5 Firestore Operation Budget

## Overview

This document defines the V5 bot's Firestore (Cloud Firestore) operation budget: the maximum reads and writes per day, broken down by operation type, and the design targets to stay within daily quota limits.

**Quota Limits (Hard):**
- Reads: 50,000 per day
- Writes: 20,000 per day
- Reset: Daily at midnight Pacific Time (09:00 GMT+2 / 07:00 UTC)

**Design Targets (Soft Caps):**
- Reads: 4,000 per day (8% of limit) — soft cap for normal operations
- Writes: 1,500 per day (7.5% of limit) — soft cap for normal operations
- Quota state transitions to WARNING when approaching soft caps
- HARD_STOP enforced at 8,000 reads or 3,000 writes (hard cap)

---

## Dashboard Write Cadence Correction

**Previous Incorrect Design:**
- 1 dashboard write per minute (1,440/day) — exceeded soft cap of 1,500W
- **Problem:** Did not follow coalesced server-side snapshot pattern

**Corrected Design:**
- 1 dashboard write per 5 minutes (288/day) — **well below soft cap**
- **Pattern:** Server-side snapshot coalesced at fixed intervals, not per operation
- **Rationale:** Dashboard refresh is a read-heavy operation on Android; writes only update the snapshot when material state changes

---

## Separation: Bot Writes vs. Android Reads

**Key Principle:**
- Bot writes persist trade lifecycle and learning state (permanent Firebase records)
- Android reads fetch current metrics for display (no side effects)
- Quota guard tracks these **separately** to ensure:
  - Bot writes stay under hard cap (3,000 writes/day safety margin)
  - Android reads scale without affecting bot write budget
  - Bot functionality not blocked by Android client load

---

## Daily Budget Summary

### Normal Operations (1-2 trades, 1 Android device)
- **Reads:** ~2,713/day (5.4% of 50k)
- **Writes:** ~313/day (1.5% of 20k)
- **Status:** ✅ Well below all limits

### Peak Operations (10 trades, 5 Android devices)
- **Reads:** ~14,028/day (28% of 50k)
- **Writes:** ~344/day (1.7% of 20k)
- **Status:** ✅ Both within limits with safety margin

---

## Conclusion

V5 is designed to stay well below Firestore quota limits with proper separation of bot writes and Android reads, coalesced dashboard snapshots, and full cost/funding provenance tracking.
