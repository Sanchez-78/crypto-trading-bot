#!/usr/bin/env python3
"""
Phase 2B: Firebase Schema Probe (Max 10 reads)

Execute minimal Firebase read operations to verify schema assumptions
before committing to Phase 2 full read (100+ documents).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Initialize Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    key_b64 = os.getenv("FIREBASE_KEY_BASE64")
    if not key_b64:
        print("ERROR: FIREBASE_KEY_BASE64 not set. Cannot execute Firebase probe.")
        sys.exit(1)

    import base64
    cred = credentials.Certificate(json.loads(base64.b64decode(key_b64)))

    if firebase_admin._apps:
        db = firestore.client()
    else:
        firebase_admin.initialize_app(cred)
        db = firestore.client()

    print("[Firebase] connected successfully")
except Exception as e:
    print(f"ERROR initializing Firebase: {e}")
    sys.exit(1)

# Read ledger
ledger = []
cumulative_reads = 0
MAX_READS = 10

def record_operation(op_num, purpose, query_desc, limit, actual_reads, success, notes=""):
    global cumulative_reads
    cumulative_reads += actual_reads
    ledger.append({
        "operation": op_num,
        "purpose": purpose,
        "query": query_desc,
        "requested_limit": limit,
        "actual_reads": actual_reads,
        "cumulative_reads": cumulative_reads,
        "success": success,
        "notes": notes,
    })
    print(f"\n[OP {op_num}] {purpose}")
    print(f"  Query: {query_desc}")
    print(f"  Limit: {limit}, Actual reads: {actual_reads}, Cumulative: {cumulative_reads}/{MAX_READS}")
    if notes:
        print(f"  Notes: {notes}")

# ── Operation 1: Unfiltered collection existence check
print("\n" + "="*80)
print("OPERATION 1: Unfiltered 'trades' collection")
print("="*80)

try:
    docs = list(db.collection("trades").limit(2).stream())
    doc_count = len(docs)
    actual_reads_op1 = max(1, doc_count)  # At least 1 read per operation

    field_names = set()
    sample_values = {}
    for doc in docs:
        data = doc.to_dict()
        field_names.update(data.keys())
        if not sample_values:
            sample_values = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}

    record_operation(
        1,
        "Verify collection exists; inspect structure",
        'db.collection("trades").limit(2)',
        2,
        actual_reads_op1,
        True,
        f"Found {doc_count} documents. Fields: {', '.join(sorted(field_names))}"
    )

    print(f"\n  Sample document keys: {sorted(field_names)}")
    if sample_values:
        print(f"  Sample values (first doc):")
        for k, v in list(sample_values.items())[:5]:
            print(f"    {k}: {repr(v)}")

except Exception as e:
    print(f"ERROR in Operation 1: {e}")
    record_operation(1, "Verify collection exists", 'db.collection("trades").limit(2)', 2, 0, False, str(e))
    sys.exit(1)

# ── Operation 2: Closed-trade filter
print("\n" + "="*80)
print("OPERATION 2: Filter by status='closed'")
print("="*80)

if cumulative_reads >= MAX_READS:
    print(f"Skipping: cumulative reads ({cumulative_reads}) >= max ({MAX_READS})")
    record_operation(2, "Verify closed-trade filter", 'status=="closed" filter', 2, 0, False, "Skipped: quota exhausted")
else:
    try:
        docs = list(db.collection("trades").where("status", "==", "closed").limit(2).stream())
        doc_count = len(docs)
        actual_reads_op2 = max(1, doc_count)

        field_names_op2 = set()
        for doc in docs:
            field_names_op2.update(doc.to_dict().keys())

        record_operation(
            2,
            "Verify closed-trade filter",
            'status=="closed" filter, limit 2',
            2,
            actual_reads_op2,
            True,
            f"Found {doc_count} closed trades. Fields: {', '.join(sorted(field_names_op2))}"
        )

        print(f"\n  Fields in closed trades: {sorted(field_names_op2)}")

    except Exception as e:
        print(f"ERROR in Operation 2: {e}")
        record_operation(2, "Verify closed-trade filter", 'status=="closed"', 2, 0, False, str(e))

# ── Operation 3: Recent closed trades with ordering
print("\n" + "="*80)
print("OPERATION 3: Recent trades with timestamp ordering")
print("="*80)

if cumulative_reads >= MAX_READS:
    print(f"Skipping: cumulative reads ({cumulative_reads}) >= max ({MAX_READS})")
    record_operation(3, "Verify ordering; check MFE/MAE fields", "exit_ts DESC ordering", 2, 0, False, "Skipped: quota exhausted")
else:
    try:
        # Try exit_ts first, fall back to timestamp if not available
        docs = list(
            db.collection("trades")
            .where("status", "==", "closed")
            .order_by("exit_ts", direction=firestore.Query.DESCENDING)
            .limit(2)
            .stream()
        )
        doc_count = len(docs)
        actual_reads_op3 = max(1, doc_count)

        mfe_mae_fields = set()
        for doc in docs:
            data = doc.to_dict()
            if "max_seen" in data or "min_seen" in data or "mfe_pct" in data or "mae_pct" in data:
                mfe_mae_fields.update(
                    k for k in ["max_seen", "min_seen", "mfe_pct", "mae_pct"] if k in data
                )

        record_operation(
            3,
            "Verify ordering; check MFE/MAE fields",
            'status=="closed" ORDER BY exit_ts DESC LIMIT 2',
            2,
            actual_reads_op3,
            True,
            f"Found {doc_count} recent trades. MFE/MAE fields present: {mfe_mae_fields if mfe_mae_fields else 'NONE'}"
        )

        if mfe_mae_fields:
            print(f"\n  ✅ MFE/MAE fields PRESENT: {mfe_mae_fields}")
            for doc in docs:
                data = doc.to_dict()
                for field in mfe_mae_fields:
                    if field in data:
                        print(f"    {field}: {repr(data[field])}")
        else:
            print(f"\n  ⚠️  MFE/MAE fields NOT FOUND in sample")

    except Exception as e:
        print(f"ERROR in Operation 3: {e}")
        record_operation(3, "Verify ordering; check MFE/MAE fields", "exit_ts DESC", 2, 0, False, str(e))

# ── Final summary
print("\n" + "="*80)
print("PHASE 2B PROBE SUMMARY")
print("="*80)

print(f"\nTotal Firebase reads used: {cumulative_reads}/{MAX_READS}")
print(f"Remaining budget: {MAX_READS - cumulative_reads}")

# Determine readiness
readiness = "UNKNOWN"
if cumulative_reads > 0:
    all_success = all(op["success"] for op in ledger)
    if all_success:
        has_mfe_mae = any("MFE/MAE fields PRESENT" in op.get("notes", "") for op in ledger)
        if has_mfe_mae:
            readiness = "READY"
        else:
            readiness = "PARTIALLY_READY"
    else:
        readiness = "NOT_READY"

print(f"\nReadiness classification: {readiness}")

# Write ledger
output_dir = "data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22"
os.makedirs(output_dir, exist_ok=True)

ledger_path = os.path.join(output_dir, "PHASE2B_PROBE_RESULTS.json")
with open(ledger_path, "w") as f:
    json.dump({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cumulative_reads": cumulative_reads,
        "max_reads": MAX_READS,
        "readiness": readiness,
        "operations": ledger,
    }, f, indent=2)

print(f"\n✅ Probe results saved to: {ledger_path}")

