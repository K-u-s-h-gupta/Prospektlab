"""Reset IKG data tables in Supabase/Postgres.

Usage:
  uv run python scripts/reset_ikg_data.py
  uv run python scripts/reset_ikg_data.py --yes
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from finagent.ikg.db import connect_postgres, get_database_url

TABLES = [
    "ikg_edges",
    "ikg_vertices",
    "concall_transcripts_raw",
    "corporate_filings_raw",
    "enforcement_raw",
    "shp_raw",
    "daily_prices",
    "company_financials",
    "directors_raw",
    "director_source_records",
    "sebi_corporate_filing_map",
    "ikg_company_master",
    "ikg_pipeline_runs",
    "ikg_scheduler_locks",
]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset IKG tables")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    _load_dotenv(Path(".env"))
    db_url = get_database_url()
    if not db_url:
        print("ERROR: No DB URL found. Set IKG_DATABASE_URL / DATABASE_URL / SUPABASE_DB_URL in .env")
        return 1

    print("This will permanently delete IKG data from these tables:")
    for t in TABLES:
        print(f"  - {t}")

    if not args.yes:
        confirm = input("Type YES to continue: ").strip()
        if confirm != "YES":
            print("Aborted.")
            return 0

    truncate_sql = (
        "TRUNCATE TABLE "
        + ", ".join(TABLES)
        + " RESTART IDENTITY CASCADE;"
    )

    try:
        with connect_postgres(db_url, connect_timeout=20) as conn:
            with conn.cursor() as cur:
                cur.execute(truncate_sql)
            conn.commit()
        print("Done. IKG tables truncated successfully.")
        return 0
    except Exception as exc:
        print(f"ERROR: Failed to reset tables: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
