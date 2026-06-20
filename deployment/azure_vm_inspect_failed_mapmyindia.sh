#!/usr/bin/env bash
set -euo pipefail

docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select
  coalesce(source_uid,'') as source_uid,
  coalesce(attachment_url,'') as attachment_url,
  coalesce(attachment_extraction_error,'') as attachment_extraction_error,
  coalesce(attachment_content_type,'') as attachment_content_type
from corporate_filings_raw
where (cin='L74899DL1995PLC065551' or upper(coalesce(symbol,''))='MAPMYINDIA')
  and coalesce(attachment_extraction_status,'')='failed'
order by announced_at desc nulls last
limit 3;
"

