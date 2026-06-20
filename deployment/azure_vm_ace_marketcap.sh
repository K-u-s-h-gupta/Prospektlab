#!/usr/bin/env bash
set -euo pipefail

docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select
  nse_symbol,
  coalesce(
    validated_metrics_json->>'market_cap',
    validated_metrics_json->>'marketCap',
    validated_metrics_json->>'market_cap_inr',
    validated_metrics_json->>'mcap',
    ''
  ) as market_cap_raw
from company_financials
where upper(coalesce(nse_symbol,'')) = 'ACE'
limit 1;
"
