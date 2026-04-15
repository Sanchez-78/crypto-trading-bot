#!/usr/bin/env python3
"""Simple Firebase reset script (no unicode issues)."""

import sys
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

from src.services.firebase_client import db

def reset_firestore():
    """Delete all documents in main collections."""
    collections = ["trades", "signals", "metrics", "calibrator", "history"]
    
    for coll_name in collections:
        try:
            # Get all docs in collection
            docs = db.collection(coll_name).stream()
            count = 0
            for doc in docs:
                db.collection(coll_name).document(doc.id).delete()
                count += 1
            
            if count > 0:
                print(f"[OK] Cleared {coll_name}: {count} documents")
            else:
                print(f"[OK] {coll_name}: already empty")
        except Exception as e:
            print(f"[WARN] {coll_name}: {str(e)[:80]}")
    
    print("\n[DONE] Firebase reset complete")
    print("[INFO] Bot is ready for fresh learning cycle")

if __name__ == "__main__":
    reset_firestore()
