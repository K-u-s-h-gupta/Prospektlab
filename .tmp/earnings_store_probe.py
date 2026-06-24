import sys
sys.path.insert(0, r"D:\PROSPEKTLAB\backend")
from psycopg.rows import dict_row
from finagent.ikg.db import connect_postgres
import json
symbol = "ITC"
date = "2026-05-21"
with connect_postgres(row_factory=dict_row, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            select a.symbol, a.meeting_date::text as date, a.processing_status,
                   d.event_uid is not null as has_detail,
                   d.parser_version,
                   jsonb_array_length(coalesce(d.financials_json->'rows', '[]'::jsonb)) as financial_rows
            from earnings_announcements a
            left join earnings_details d on d.event_uid = a.event_uid
            where a.symbol = %s and a.meeting_date = %s
            order by a.updated_at desc
            limit 1
        """, (symbol, date))
        print(json.dumps(dict(cur.fetchone() or {}), default=str))