import sys
sys.path.insert(0, r"D:\PROSPEKTLAB\backend")
from psycopg.rows import dict_row
from finagent.ikg.db import connect_postgres
import json
with connect_postgres(row_factory=dict_row, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            select a.symbol, a.meeting_date::text as date, a.company_name, a.processing_status,
                   coalesce(jsonb_array_length(a.attachment_urls), 0) as attachments
            from earnings_announcements a
            left join earnings_details d on d.event_uid = a.event_uid
            where a.meeting_date <= current_date
              and d.event_uid is null
              and coalesce(a.processing_status, '') <> 'parsing'
            order by a.meeting_date desc
            limit 5
        """)
        print(json.dumps([dict(row) for row in cur.fetchall()], default=str))