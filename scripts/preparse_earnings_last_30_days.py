import os
os.environ["FINAGENT_EARNINGS_FILTER_UNIVERSE"] = "false"

from datetime import date, timedelta
from finagent.ikg.db import connect_postgres, get_database_url
from finagent.earnings.service import ensure_earnings_detail_for_result

url = get_database_url()
if not url:
    raise SystemExit("No database URL")

with connect_postgres(connect_timeout=5) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT symbol, meeting_date
            FROM earnings_announcements
            WHERE meeting_date < CURRENT_DATE AND meeting_date >= CURRENT_DATE - 30
            ORDER BY meeting_date DESC, symbol
        """)
        rows = cur.fetchall()

print(f"Pre-parsing {len(rows)} companies from last 30 days")
for i, (symbol, meeting_date) in enumerate(rows):
    try:
        result = ensure_earnings_detail_for_result(symbol, str(meeting_date))
        print(f"{i+1}/{len(rows)} {symbol} {meeting_date}: {result.get('reason') or result.get('stored')}")
    except Exception as exc:
        print(f"{i+1}/{len(rows)} {symbol} {meeting_date}: ERROR {exc}")

print("Done")
