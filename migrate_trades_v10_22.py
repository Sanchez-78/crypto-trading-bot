"""
V10.22: Migrate trades from old learning_database.sqlite to new cache.sqlite
Also recalculate learning metrics based on V10.22 improvements.
"""

import sqlite3
import json
from pathlib import Path

OLD_DB = Path('/opt/cryptomaster/local_learning_storage/learning_database.sqlite')
NEW_DB = Path('/opt/cryptomaster/local_learning_storage/cache.sqlite')

def migrate_trades():
    """Migrate 75 trades from old to new database."""

    if not OLD_DB.exists():
        print("❌ Old database not found")
        return False

    # Connect to both databases
    old_conn = sqlite3.connect(str(OLD_DB), timeout=5)
    new_conn = sqlite3.connect(str(NEW_DB), timeout=5)

    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()

    try:
        # Get all trades from old DB
        old_cursor.execute('SELECT * FROM trades')
        trades = old_cursor.fetchall()

        print(f"📊 Found {len(trades)} trades in old database")

        # Get column names
        old_cursor.execute("PRAGMA table_info(trades)")
        columns = [col[1] for col in old_cursor.fetchall()]

        # Migrate each trade
        for i, trade in enumerate(trades):
            # Create dict from trade
            trade_dict = dict(zip(columns, trade))

            # Insert into new DB
            try:
                new_cursor.execute(f"""
                    INSERT INTO closed_trades (
                        trade_id, symbol, entry_ts, exit_ts, entry_price,
                        exit_price, pnl_usd, pnl_pct, win, exit_reason,
                        regime, mfe, mae, synced_to_firebase
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    trade_dict.get('id'),
                    trade_dict.get('symbol'),
                    trade_dict.get('entry_ts'),
                    trade_dict.get('exit_ts'),
                    trade_dict.get('entry_price'),
                    trade_dict.get('exit_price'),
                    trade_dict.get('pnl_usd'),
                    trade_dict.get('pnl_pct'),
                    1 if trade_dict.get('pnl_usd', 0) > 0 else 0,
                    trade_dict.get('close_reason', 'TIMEOUT'),
                    trade_dict.get('regime', 'RANGING'),
                    trade_dict.get('mfe'),
                    trade_dict.get('mae'),
                ))
            except Exception as e:
                print(f"  ⚠️  Trade {i}: {e}")
                continue

        new_conn.commit()
        print(f"✅ Migrated {len(trades)} trades to new database")

        # Calculate metrics
        stats = calculate_metrics(new_cursor)
        print(f"📈 Learning metrics calculated: {stats}")

        # Save metrics
        save_learning_metrics(new_cursor, stats)

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    finally:
        old_conn.close()
        new_conn.close()

def calculate_metrics(cursor):
    """Calculate learning metrics from migrated trades."""

    cursor.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl_usd) as net_pnl,
            AVG(pnl_usd) as avg_pnl
        FROM closed_trades
    ''')

    row = cursor.fetchone()
    total, wins, losses, net_pnl, avg_pnl = row

    wins = wins or 0
    losses = losses or 0
    net_pnl = net_pnl or 0
    avg_pnl = avg_pnl or 0

    # Calculate profit factor
    cursor.execute('''
        SELECT
            SUM(CASE WHEN pnl_usd > 0 THEN ABS(pnl_usd) ELSE 0 END) as wins_usd,
            SUM(CASE WHEN pnl_usd < 0 THEN ABS(pnl_usd) ELSE 0 END) as losses_usd
        FROM closed_trades
    ''')

    wins_usd, losses_usd = cursor.fetchone()
    wins_usd = wins_usd or 0
    losses_usd = losses_usd or 0

    pf = wins_usd / losses_usd if losses_usd > 0 else 0
    wr = wins / total if total > 0 else 0
    exp = avg_pnl

    return {
        'total_trades': total,
        'wins': wins,
        'losses': losses,
        'profit_factor': pf,
        'win_rate': wr,
        'expectancy': exp,
        'net_pnl': net_pnl,
    }

def save_learning_metrics(cursor, stats):
    """Save calculated metrics to learning_metrics table."""

    import time

    try:
        cursor.execute('''
            INSERT INTO learning_metrics (
                timestamp, total_trades, wins, losses, profit_factor,
                expectancy, win_rate, net_pnl, learning_version, synced_to_firebase
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (
            time.time(),
            stats['total_trades'],
            stats['wins'],
            stats['losses'],
            stats['profit_factor'],
            stats['expectancy'],
            stats['win_rate'],
            stats['net_pnl'],
            'V10.22-MIGRATED',
        ))

        cursor.connection.commit()
        print("✅ Learning metrics saved")

    except Exception as e:
        print(f"⚠️  Could not save metrics: {e}")

if __name__ == '__main__':
    print("=" * 70)
    print("V10.22 TRADE MIGRATION: OLD → NEW LOCAL-FIRST CACHE")
    print("=" * 70)
    print()

    success = migrate_trades()

    print()
    if success:
        print("✅ MIGRATION COMPLETE")
        print("   Next: Bot will continue trading with V10.22 fixes")
        print("   Learning will track all 75 historical + new trades")
    else:
        print("❌ MIGRATION FAILED - Please investigate")

    print("=" * 70)
