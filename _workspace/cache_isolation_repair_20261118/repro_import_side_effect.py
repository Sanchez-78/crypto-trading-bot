"""Synthetic reproduction of local_persistent_cache's import-time write (no real runtime DB).

Each import runs in a fresh interpreter with cwd = a private temp dir, so the module's
relative LOCAL_DB_PATH resolves inside the temp dir. The real local_learning_storage/
cache.sqlite is hashed before and after; any change aborts.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "local_learning_storage" / "cache.sqlite"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def import_in(cwd: Path) -> None:
    code = "import sys; sys.path.insert(0, sys.argv[1]); import src.services.local_persistent_cache"
    subprocess.run([sys.executable, "-B", "-c", code, str(ROOT)], cwd=cwd, check=True, capture_output=True)


def info(db: Path) -> dict:
    c = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    cols = [r[1] for r in c.execute("pragma table_info(closed_trades)")]
    rows = c.execute("select count(*) from closed_trades").fetchone()[0]
    ver = c.execute("pragma schema_version").fetchone()[0]
    c.close()
    return {"sha256": sha(db), "schema_version": ver, "columns": len(cols), "rows": rows, "last_cols": cols[-2:]}


def main() -> int:
    real_before = sha(REAL)
    out = {"real_db_before": real_before}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        db = tmp / "local_learning_storage" / "cache.sqlite"
        import_in(tmp)                                  # creates a fresh synthetic DB
        c = sqlite3.connect(db)
        c.execute("insert into closed_trades (trade_id, symbol, entry_ts, pnl_usd) values ('syn1','BTCUSDT',1.0,0.1)")
        c.commit(); c.close()
        out["fresh"] = info(db)
        import_in(tmp)                                  # 1) import over an up-to-date schema
        out["after_reimport_current_schema"] = info(db)
        c = sqlite3.connect(db)                         # 2) older schema: drop the two newest columns
        c.execute("alter table closed_trades drop column predicted_net_edge_bps")
        c.execute("alter table closed_trades drop column predicted_gross_move_bps")
        c.commit(); c.close()
        out["older_schema"] = info(db)
        import_in(tmp)
        out["after_import_older_schema"] = info(db)
    out["real_db_after"] = sha(REAL)
    out["real_db_unchanged"] = out["real_db_before"] == out["real_db_after"]
    out["current_schema_import_changes_hash"] = out["fresh"]["sha256"] != out["after_reimport_current_schema"]["sha256"]
    out["older_schema_import_changes_hash"] = out["older_schema"]["sha256"] != out["after_import_older_schema"]["sha256"]
    Path(__file__).with_name("repro_import_side_effect.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if out["real_db_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
