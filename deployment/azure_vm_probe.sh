#!/usr/bin/env bash
set -euo pipefail

echo "host=$(hostname)"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo "---"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "select count(*) from company_financials;"
echo "---"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "select nse_symbol, coalesce(cin,''), coalesce(bse_scrip_code,''), coalesce(company_name,'') from ikg_company_master where nse_symbol is not null order by company_name limit 20;"
