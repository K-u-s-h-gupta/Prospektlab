"""Bootstrap Supabase database tables and verify they exist."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv("finagent/.env")

from finagent.ikg.db import connect_postgres, get_database_url

db = get_database_url()
if not db:
    print("ERROR: No database URL configured")
    sys.exit(1)

print(f"DB: {db[:50]}...")

# Read and execute bootstrap SQL
with open("deployment/ikg_db_bootstrap.sql", "r") as f:
    sql = f.read()

with connect_postgres(db, connect_timeout=30) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print("Bootstrap SQL executed successfully!")

# Verify tables exist
with connect_postgres(db, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nTables in DB ({len(tables)}):")
        for t in tables:
            cur.execute(f"SELECT count(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"  {t:<40} {count:>8} rows")
