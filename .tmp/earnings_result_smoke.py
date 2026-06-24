import sys
sys.path.insert(0, r"D:\PROSPEKTLAB\backend")
from psycopg.rows import dict_row
from finagent.ikg.db import connect_postgres
from finagent.earnings.service import get_earnings_result
import json

row = None
with connect_postgres(row_factory=dict_row, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            select a.symbol, a.meeting_date::text as date, a.company_name, d.event_uid as detail_uid
            from earnings_announcements a
            left join earnings_details d on d.event_uid = a.event_uid
            where a.meeting_date <= current_date
            order by case when d.event_uid is null then 0 else 1 end, a.meeting_date desc
            limit 1
            """
        )
        fetched = cur.fetchone()
        row = dict(fetched) if fetched else {}
print(json.dumps(row, default=str))
if row:
    result = get_earnings_result(row["symbol"], row["date"])
    if result:
        print(json.dumps({
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "meeting_date": result.get("meeting_date"),
            "financials": result.get("financials"),
            "documents": result.get("documents"),
            "highlights_count": len(result.get("highlights") or []),
        }, default=str)[:2500])
    else:
        print("null")