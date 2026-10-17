import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('runtime/opendub.sqlite3')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('Tables in runtime/opendub.sqlite3:')
for t in tables:
    count = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {count} rows")
    if count > 0:
        cur.execute(f"SELECT * FROM {t} LIMIT 3")
        cols = [d[0] for d in cur.description]
        print(f"    Columns: {cols}")
        for r in cur.fetchall():
            print(f"    Row: {r[:6]}")
