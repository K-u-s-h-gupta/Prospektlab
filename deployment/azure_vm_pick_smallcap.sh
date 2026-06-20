#!/usr/bin/env bash
set -euo pipefail

docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
with mc as (
  select distinct on (upper(coalesce(cf.nse_symbol,'')))
    upper(coalesce(cf.nse_symbol,'')) as nse_symbol,
    coalesce(
      nullif(cf.validated_metrics_json->'market_cap'->>'value','')::numeric,
      nullif(regexp_replace(
        coalesce(
          cf.validated_metrics_json->>'market_cap',
          cf.validated_metrics_json->>'marketCap',
          cf.validated_metrics_json->>'market_cap_inr',
          cf.validated_metrics_json->>'mcap',
          ''
        ),
        '[^0-9.]',
        '',
        'g'
      ),'')::numeric
    ) as mcap_inr
  from company_financials cf
  where coalesce(cf.nse_symbol,'') <> ''
)
select
  mc.nse_symbol,
  coalesce(cm.cin,''),
  coalesce(cm.bse_scrip_code,''),
  coalesce(cm.company_name,''),
  round(mc.mcap_inr / 10000000.0, 2) as mcap_cr
from mc
join ikg_company_master cm on upper(coalesce(cm.nse_symbol,'')) = mc.nse_symbol
where cm.listing_status ilike 'listed'
  and mc.mcap_inr is not null
  and mc.mcap_inr > 0
order by mc.mcap_inr asc
limit 25;
"
