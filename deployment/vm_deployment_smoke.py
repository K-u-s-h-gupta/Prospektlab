from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from shutil import which


ROOT = Path(__file__).resolve().parents[1]
REMOTE_HOST_SCRAPER = "/home/azureuser/backend/finagent/ikg/scrapers/sebi_corporate_filings.py"
REMOTE_CONTAINER_SCRAPER = "/app/finagent/ikg/scrapers/sebi_corporate_filings.py"
REMOTE_HOST_MCA = "/home/azureuser/backend/finagent/ikg/scrapers/mca_companies.py"
REMOTE_CONTAINER_MCA = "/app/finagent/ikg/scrapers/mca_companies.py"
REMOTE_HOST_BSE_SHP = "/home/azureuser/backend/finagent/ikg/scrapers/bse_shp.py"
REMOTE_CONTAINER_BSE_SHP = "/app/finagent/ikg/scrapers/bse_shp.py"
REMOTE_HOST_ORCHESTRATOR = "/home/azureuser/backend/finagent/ikg/pipeline/orchestrator.py"
REMOTE_CONTAINER_ORCHESTRATOR = "/app/finagent/ikg/pipeline/orchestrator.py"
LOCAL_TARGET_SMOKE = ROOT / "backend" / "finagent" / "ikg" / "pipeline" / "target_company_smoke.py"
REMOTE_HOST_TARGET_SMOKE = "/home/azureuser/backend/finagent/ikg/pipeline/target_company_smoke.py"
REMOTE_CONTAINER_TARGET_SMOKE = "/app/finagent/ikg/pipeline/target_company_smoke.py"
AZ_CLI = which("az") or which("az.cmd") or r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
TARGET_CONTAINERS = [
    "deployment-scheduler-1",
    "deployment-celery-worker-2",
    "deployment-celery-worker-3",
    "deployment-celery-worker-4",
]


def _extract_block(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx].rstrip() + "\n"


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, check=False, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed rc={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _az_invoke(resource_group: str, vm_name: str, script: str) -> dict:
    proc = _run(
        [
            AZ_CLI,
            "vm",
            "run-command",
            "invoke",
            "-g",
            resource_group,
            "-n",
            vm_name,
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            "-o",
            "json",
        ]
    )
    return json.loads(proc.stdout)


def _message_text(payload: dict) -> str:
    value = (payload.get("value") or [{}])[0]
    return str(value.get("message") or "")


def _print_remote(payload: dict) -> None:
    text = _message_text(payload)
    if text:
        print(text)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def patch_scraper(resource_group: str, vm_name: str) -> None:
    scripts = [
        f"""
python3 -c "from pathlib import Path
p = Path('{REMOTE_HOST_MCA}')
t = p.read_text(encoding='utf-8')
old = '        sql += \" order by company_name\"'
new = '''        sql += (
            \" order by \"
            \"case when cin is not null and trim(cin) <> '' then 0 else 1 end, \"
            \"case when bse_scrip_code is not null and trim(bse_scrip_code) <> '' then 0 else 1 end, \"
            \"company_name\"
        )'''
if old not in t:
    raise SystemExit('mca order pattern not found')
t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')
print('patched_mca=1')"
""",
        f"""
python3 -c "from pathlib import Path
p = Path('{REMOTE_HOST_BSE_SHP}')
t = p.read_text(encoding='utf-8')
replacements = [
    ('_DEFAULT_MAX_WORKERS = 4\\n', '_DEFAULT_MAX_WORKERS = 4\\n_DEFAULT_DISCOVERY_TIMEOUT_S = float(os.getenv(\"FINAGENT_BSE_SHP_DISCOVERY_TIMEOUT_S\", \"45\") or \"45\")\\n_DEFAULT_REQUEST_TIMEOUT_S = float(os.getenv(\"FINAGENT_BSE_SHP_REQUEST_TIMEOUT_S\", \"20\") or \"20\")\\n'),
    ('    retries: int = 2,\\n) -> dict[str, Any]:', '    retries: int = 2,\\n    allow_list: bool = False,\\n) -> dict[str, Any] | list[Any]:'),
    ('            payload = resp.json()\\n            if not isinstance(payload, dict):', '            payload = resp.json()\\n            if allow_list and isinstance(payload, list):\\n                return payload\\n            if not isinstance(payload, dict):'),
    ('    resp = client.get(_BSE_SHP_DECLARATION_URL.format(scrip_code=scrip_code), headers=_BSE_HEADERS)\\n    resp.raise_for_status()\\n    declaration = resp.json()', '    declaration_resp = _fetch_json(\\n        client,\\n        _BSE_SHP_DECLARATION_URL.format(scrip_code=scrip_code),\\n        retries=3,\\n        allow_list=True,\\n    )\\n    declaration = declaration_resp if isinstance(declaration_resp, list) else declaration_resp.get(\"Table\") or declaration_resp.get(\"data\") or []'),
    ('            with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=False) as client:', '            timeout = httpx.Timeout(_DEFAULT_DISCOVERY_TIMEOUT_S, connect=min(15.0, _DEFAULT_DISCOVERY_TIMEOUT_S))\\n            with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:'),
    ('            shp_data = fetch_bse_shp(scrip_code, qtr_id)', '            shp_data = fetch_bse_shp(scrip_code, qtr_id, timeout_s=_DEFAULT_REQUEST_TIMEOUT_S)'),
]
for old, new in replacements:
    if old not in t:
        raise SystemExit('bse_shp pattern not found: ' + old[:40])
    t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')
print('patched_bse_shp=1')"
""",
        f"""
python3 -c "from pathlib import Path
p = Path('{REMOTE_HOST_ORCHESTRATOR}')
t = p.read_text(encoding='utf-8')
old = '''        cins = {{str(co.get(\"cin\") or \"\").strip() for co in companies if co.get(\"cin\")}}
        if not cins:
            result.error = \"No company CINs found for graph build\"
            result.success = False
        else:
            stats = build_ikg_from_staging(database_url=_DATABASE_URL, nifty10_cins=cins)
            result.records_fetched = len(cins)
            result.records_stored = int(stats.get(\"vertices_created\", 0)) + int(stats.get(\"edges_created\", 0))
            result.records_failed = 1 if stats.get(\"error\") else 0
            result.success = not bool(stats.get(\"error\"))
            result.error = stats.get(\"error\")
            result.metadata.update(stats)'''
new = '''        cins = {{str(co.get(\"cin\") or \"\").strip() for co in companies if co.get(\"cin\")}}
        if not cins:
            refs = {{
                str(
                    co.get(\"nse_symbol\")
                    or co.get(\"bse_scrip_code\")
                    or co.get(\"isin\")
                    or co.get(\"company_name\")
                    or \"\"
                ).strip()
                for co in companies
                if (
                    co.get(\"nse_symbol\")
                    or co.get(\"bse_scrip_code\")
                    or co.get(\"isin\")
                    or co.get(\"company_name\")
                )
            }}
            allow_broad_fallback = os.getenv(
                \"FINAGENT_IKG_BUILD_BROAD_FALLBACK_ON_MISSING_CINS\",
                \"1\",
            ).strip().lower() in {{\"1\", \"true\", \"yes\", \"on\"}}
            if refs and allow_broad_fallback:
                logger.warning(
                    \"No company CINs found for scoped graph build; falling back to broad staging build for %d scoped refs\",
                    len(refs),
                )
                stats = build_ikg_from_staging(database_url=_DATABASE_URL, nifty10_cins=None)
                result.records_fetched = len(refs)
                result.records_stored = int(stats.get(\"vertices_created\", 0)) + int(stats.get(\"edges_created\", 0))
                result.records_failed = 1 if stats.get(\"error\") else 0
                result.success = not bool(stats.get(\"error\"))
                result.error = stats.get(\"error\")
                result.metadata.update(
                    {{
                        \"scope_fallback\": \"broad_no_cin_filter\",
                        \"scoped_refs\": sorted(refs)[:10],
                    }}
                )
                result.metadata.update(stats)
            else:
                result.error = \"No company CINs found for graph build\"
                result.success = False
                result.metadata[\"scope_fallback\"] = \"disabled\" if refs else \"no_scope_refs\"
        else:
            stats = build_ikg_from_staging(database_url=_DATABASE_URL, nifty10_cins=cins)
            result.records_fetched = len(cins)
            result.records_stored = int(stats.get(\"vertices_created\", 0)) + int(stats.get(\"edges_created\", 0))
            result.records_failed = 1 if stats.get(\"error\") else 0
            result.success = not bool(stats.get(\"error\"))
            result.error = stats.get(\"error\")
            result.metadata.update(stats)'''
if old not in t:
    raise SystemExit('orchestrator graph block pattern not found')
t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')
print('patched_orchestrator=1')"
""",
    ]
    for script in scripts:
        _print_remote(_az_invoke(resource_group, vm_name, script))

    copy_script = f"""
set -e
for c in {' '.join(TARGET_CONTAINERS)}; do
  if docker ps --format '{{{{.Names}}}}' | grep -qx "$c"; then
    docker cp {REMOTE_HOST_MCA} "$c:{REMOTE_CONTAINER_MCA}"
    docker cp {REMOTE_HOST_BSE_SHP} "$c:{REMOTE_CONTAINER_BSE_SHP}"
    docker cp {REMOTE_HOST_ORCHESTRATOR} "$c:{REMOTE_CONTAINER_ORCHESTRATOR}"
    docker restart "$c" >/dev/null
    echo "updated_container=$c"
  fi
done
"""
    _print_remote(_az_invoke(resource_group, vm_name, copy_script))


def verify_scraper(resource_group: str, vm_name: str) -> None:
    verify_script = f"""
python3 -c "from pathlib import Path
paths = ['{REMOTE_HOST_SCRAPER}', '{REMOTE_CONTAINER_SCRAPER}']
host = Path(paths[0]).read_text(encoding='utf-8')
print('host_helper=' + str(int('def _store_corporate_action_for_record' in host)))
print('host_hydrate=' + str(int('corporate_actions_stored' in host and 'xbrl_filings' in host)))
"
docker exec deployment-scheduler-1 python -c "from pathlib import Path
text = Path('{REMOTE_CONTAINER_SCRAPER}').read_text(encoding='utf-8')
print('container_helper=' + str(int('def _store_corporate_action_for_record' in text)))
print('container_hydrate=' + str(int('corporate_actions_stored' in text and 'xbrl_filings' in text)))
"
"""
    _print_remote(_az_invoke(resource_group, vm_name, verify_script))


def db_snapshot(resource_group: str, vm_name: str, *, label: str) -> None:
    sql = (
        "select 'company_master='||count(*) from ikg_company_master "
        "union all select 'financials='||count(*) from company_financials "
        "union all select 'shp='||count(*) from shp_raw "
        "union all select 'corp_filings='||count(*) from corporate_filings_raw "
        "union all select 'corp_filings_with_text='||count(*) from corporate_filings_raw where coalesce(attachment_text_length,0) > 0 "
        "union all select 'xbrl_filings='||count(*) from xbrl_filings_raw "
        "union all select 'xbrl_facts='||count(*) from corporate_xbrl_facts "
        "union all select 'financial_xbrl='||count(*) from financial_results_xbrl "
        "union all select 'event_xbrl='||count(*) from corporate_event_xbrl "
        "union all select 'corporate_actions='||count(*) from corporate_actions_raw "
        "union all select 'annual_reports='||count(*) from annual_reports_raw "
        "union all select 'concalls='||count(*) from concall_transcripts_raw "
        "union all select 'document_sections='||count(*) from document_sections "
        "union all select 'vertices='||count(*) from ikg_vertices "
        "union all select 'edges='||count(*) from ikg_edges "
        "union all select 'facts='||count(*) from ikg_facts "
        "union all select 'runs='||count(*) from ikg_pipeline_runs"
    )
    script = f"""
echo '=== {label} ==='
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "{sql}"
"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def latest_runs(resource_group: str, vm_name: str) -> None:
    sql = (
        "select to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') || ' | ' || task_name || "
        "' | success=' || success || ' | fetched=' || coalesce(records_fetched,0) || "
        "' | stored=' || coalesce(records_stored,0) || ' | failed=' || coalesce(records_failed,0) "
        "from ikg_pipeline_runs order by created_at desc limit 15"
    )
    script = f"docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc \"{sql}\""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def health(resource_group: str, vm_name: str) -> None:
    script = (
        "docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator "
        "--phase health"
    )
    _print_remote(_az_invoke(resource_group, vm_name, script))


def upsert_company_identity(
    resource_group: str,
    vm_name: str,
    *,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
) -> None:
    symbol_sql = _sql_literal(symbol.upper())
    cin_sql = _sql_literal(cin)
    scrip_sql = _sql_literal(bse_scrip_code)
    name_sql = _sql_literal(company_name)
    script = f"""
docker exec -i deployment-postgres-1 psql -U ikg_user -d ikg -c "
update ikg_company_master
   set cin = {cin_sql},
       bse_scrip_code = coalesce(nullif(bse_scrip_code, ''), {scrip_sql}),
       company_name = coalesce(nullif(company_name, ''), {name_sql}),
       listing_status = coalesce(nullif(listing_status, ''), 'Listed'),
       status = coalesce(nullif(status, ''), 'Active'),
       updated_at = now()
 where upper(nse_symbol) = {symbol_sql};
select cin, nse_symbol, bse_scrip_code, company_name
  from ikg_company_master
 where upper(nse_symbol) = {symbol_sql};
"
"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def scoped_company_snapshot(
    resource_group: str,
    vm_name: str,
    *,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    label: str,
) -> None:
    symbol_sql = _sql_literal(symbol.upper())
    cin_sql = _sql_literal(cin)
    scrip_sql = _sql_literal(bse_scrip_code)
    sql = f"""
select 'company_master=' || count(*) from ikg_company_master
 where upper(coalesce(nse_symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(bse_scrip_code, '') = {scrip_sql}
union all
select 'financials=' || count(*) from company_financials
 where upper(coalesce(nse_symbol, '')) = {symbol_sql} or cin = {cin_sql}
union all
select 'shp=' || count(*) from shp_raw
 where cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'corp_filings=' || count(*) from corporate_filings_raw
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'corp_filings_with_text=' || count(*) from corporate_filings_raw
 where (upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql})
   and coalesce(attachment_text_length, 0) > 0
union all
select 'xbrl_filings=' || count(*) from xbrl_filings_raw
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'xbrl_facts=' || count(*) from corporate_xbrl_facts
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'financial_xbrl=' || count(*) from financial_results_xbrl
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'event_xbrl=' || count(*) from corporate_event_xbrl
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'corp_actions=' || count(*) from corporate_actions_raw
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'annual_reports=' || count(*) from annual_reports_raw
 where upper(coalesce(nse_symbol, '')) = {symbol_sql} or cin = {cin_sql} or coalesce(scrip_code, '') = {scrip_sql}
union all
select 'concalls=' || count(*) from concall_transcripts_raw
 where upper(coalesce(symbol, '')) = {symbol_sql} or cin = {cin_sql}
union all
select 'directors=' || count(*) from directors_raw
 where cin = {cin_sql} or upper(coalesce(nse_symbol, '')) = {symbol_sql}
union all
select 'sections=' || count(*) from document_sections
 where upper(coalesce(metadata->>'nse_symbol', '')) = {symbol_sql}
    or coalesce(metadata->>'cin', '') = {cin_sql}
    or coalesce(metadata->>'company_identifier', '') in ({cin_sql}, {symbol_sql}, {scrip_sql})
union all
select 'vertices=' || count(*) from ikg_vertices
 where vertex_id in ('company:' || {cin_sql}, 'company:' || {symbol_sql}, 'company:' || {scrip_sql})
union all
select 'edges=' || count(*) from ikg_edges
 where from_vertex_id in ('company:' || {cin_sql}, 'company:' || {symbol_sql}, 'company:' || {scrip_sql})
    or to_vertex_id in ('company:' || {cin_sql}, 'company:' || {symbol_sql}, 'company:' || {scrip_sql})
union all
select 'facts=' || count(*) from ikg_facts
 where subject_entity_id in ('company:' || {cin_sql}, 'company:' || {symbol_sql}, 'company:' || {scrip_sql})
    or coalesce(object_entity_id, '') in ('company:' || {cin_sql}, 'company:' || {symbol_sql}, 'company:' || {scrip_sql});
"""
    script = f"""echo '=== scoped snapshot: {label} ==='
docker exec -i deployment-postgres-1 psql -U ikg_user -d ikg -At <<'SQL'
{sql}
SQL"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def run_target_company_smoke(
    resource_group: str,
    vm_name: str,
    *,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
    years_back: int = 1,
    reports_per_company: int = 1,
) -> None:
    upsert_company_identity(
        resource_group,
        vm_name,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        company_name=company_name,
    )
    scoped_company_snapshot(
        resource_group,
        vm_name,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        label="before",
    )
    script = (
        f"docker exec -i deployment-scheduler-1 python - "
        f"--symbol {symbol} "
        f"--cin {cin} "
        f"--bse-scrip {bse_scrip_code} "
        f"--company-name \"{company_name}\" "
        f"--years-back {years_back} "
        f"--reports-per-company {reports_per_company} "
        f"--qdrant-limit 40 < {REMOTE_HOST_TARGET_SMOKE}"
    )
    _print_remote(_az_invoke(resource_group, vm_name, script))
    scoped_company_snapshot(
        resource_group,
        vm_name,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        label="after",
    )


def sync_target_smoke_module(resource_group: str, vm_name: str) -> None:
    payload = base64.b64encode(LOCAL_TARGET_SMOKE.read_bytes()).decode("ascii")
    remote_b64 = "/home/azureuser/backend/finagent/ikg/pipeline/target_company_smoke.py.b64"
    _print_remote(
        _az_invoke(
            resource_group,
            vm_name,
            f"rm -f {remote_b64}; mkdir -p /home/azureuser/backend/finagent/ikg/pipeline",
        )
    )
    chunk_size = 3000
    for idx in range(0, len(payload), chunk_size):
        chunk = payload[idx : idx + chunk_size]
        script = (
            "python3 -c "
            f"\"from pathlib import Path; Path('{remote_b64}').open('a', encoding='utf-8').write('{chunk}')\""
        )
        _az_invoke(resource_group, vm_name, script)
    script = f"""
python3 -c "from pathlib import Path; import base64
src = Path('{remote_b64}')
dst = Path('{REMOTE_HOST_TARGET_SMOKE}')
dst.write_bytes(base64.b64decode(src.read_text(encoding='utf-8')))
print('synced_host_target_smoke=1')"
for c in {' '.join(TARGET_CONTAINERS)}; do
  if docker ps --format '{{{{.Names}}}}' | grep -qx "$c"; then
    pyver=$(docker exec "$c" python -c "import sys; print(f'{{sys.version_info[0]}}.{{sys.version_info[1]}}')" 2>/dev/null || echo "3.11")
    docker cp {REMOTE_HOST_TARGET_SMOKE} "$c:{REMOTE_CONTAINER_TARGET_SMOKE}" >/dev/null 2>&1 || true
    docker cp {REMOTE_HOST_TARGET_SMOKE} "$c:/usr/local/lib/python${{pyver}}/site-packages/finagent/ikg/pipeline/target_company_smoke.py" >/dev/null 2>&1 || true
    docker exec "$c" python -c "import importlib.util; spec = importlib.util.find_spec('finagent.ikg.pipeline.target_company_smoke'); print('target_spec=' + str(spec.origin if spec else None))"
  fi
done
"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def remote_python_probe(resource_group: str, vm_name: str) -> None:
    script = """docker exec -i deployment-scheduler-1 python - <<'PY'
print("remote_python_probe_ok")
PY"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def remote_psql_probe(resource_group: str, vm_name: str) -> None:
    script = """docker exec -i deployment-postgres-1 psql -U ikg_user -d ikg -At <<'SQL'
select 'probe=' || count(*) from ikg_company_master;
SQL"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def inspect_target_module(resource_group: str, vm_name: str) -> None:
    script = f"""
echo '=== containers ==='
docker ps --format '{{{{.Names}}}}'
echo '=== host target module ==='
ls -l {REMOTE_HOST_TARGET_SMOKE} || true
echo '=== scheduler target module ==='
docker exec deployment-scheduler-1 sh -lc 'ls -l {REMOTE_CONTAINER_TARGET_SMOKE} || true'
echo '=== scheduler import probe ==='
docker exec deployment-scheduler-1 python -c "import importlib.util; spec = importlib.util.find_spec('finagent.ikg.pipeline.target_company_smoke'); print('target_spec=' + str(spec.origin if spec else None))"
"""
    _print_remote(_az_invoke(resource_group, vm_name, script))


def inspect_target_module_raw(resource_group: str, vm_name: str) -> None:
    script = f"""
echo '=== containers ==='
docker ps --format '{{{{.Names}}}}'
echo '=== host target module ==='
ls -l {REMOTE_HOST_TARGET_SMOKE} || true
echo '=== scheduler target module ==='
docker exec deployment-scheduler-1 sh -lc 'ls -l {REMOTE_CONTAINER_TARGET_SMOKE} || true'
echo '=== scheduler import probe ==='
docker exec deployment-scheduler-1 python -c "import importlib.util; spec = importlib.util.find_spec('finagent.ikg.pipeline.target_company_smoke'); print('target_spec=' + str(spec.origin if spec else None))"
"""
    print(json.dumps(_az_invoke(resource_group, vm_name, script), indent=2))


def run_smoke(resource_group: str, vm_name: str, *, max_companies: int, years_back: int) -> None:
    commands = [
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase nse",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase shp --max-companies {max_companies}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase financials --max-companies {max_companies}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase corp_filings --max-companies {max_companies} --years-back {years_back}",
        "docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase corp_filing_hydrate --max-companies 25",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase annual_reports --max-companies {max_companies}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase concall --max-companies {max_companies} --years-back {years_back}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase governance_directors --max-companies {max_companies} --years-back {years_back}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase director_kmp --max-companies {max_companies} --years-back {years_back}",
        f"docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase build_graph --max-companies {max_companies}",
        "docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase qdrant_index",
    ]
    for command in commands:
        print(f"\n>>> {command}")
        _print_remote(_az_invoke(resource_group, vm_name, command))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-group", default="PROSPEKTLAB-IKG-RG")
    parser.add_argument("--vm-name", default="prospektlab-ikg-vm")
    parser.add_argument("--max-companies", type=int, default=1)
    parser.add_argument("--years-back", type=int, default=3)
    parser.add_argument("--skip-patch", action="store_true")
    parser.add_argument("--target-symbol")
    parser.add_argument("--target-cin")
    parser.add_argument("--target-bse-scrip")
    parser.add_argument("--target-company-name")
    parser.add_argument("--reports-per-company", type=int, default=1)
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--remote-python-probe", action="store_true")
    parser.add_argument("--remote-psql-probe", action="store_true")
    parser.add_argument("--inspect-target-module", action="store_true")
    parser.add_argument("--inspect-target-module-raw", action="store_true")
    parser.add_argument("--sync-target-module", action="store_true")
    args = parser.parse_args()

    if args.remote_python_probe:
        remote_python_probe(args.resource_group, args.vm_name)
        return 0
    if args.remote_psql_probe:
        remote_psql_probe(args.resource_group, args.vm_name)
        return 0
    if args.inspect_target_module:
        inspect_target_module(args.resource_group, args.vm_name)
        return 0
    if args.inspect_target_module_raw:
        inspect_target_module_raw(args.resource_group, args.vm_name)
        return 0
    if args.sync_target_module:
        sync_target_smoke_module(args.resource_group, args.vm_name)
        return 0

    if args.target_symbol and args.target_cin and args.target_bse_scrip and args.target_company_name:
        sync_target_smoke_module(args.resource_group, args.vm_name)
        if args.snapshot_only:
            scoped_company_snapshot(
                args.resource_group,
                args.vm_name,
                symbol=args.target_symbol,
                cin=args.target_cin,
                bse_scrip_code=args.target_bse_scrip,
                label="manual_snapshot",
            )
        else:
            run_target_company_smoke(
                args.resource_group,
                args.vm_name,
                symbol=args.target_symbol,
                cin=args.target_cin,
                bse_scrip_code=args.target_bse_scrip,
                company_name=args.target_company_name,
                years_back=args.years_back,
                reports_per_company=args.reports_per_company,
            )
        try:
            health(args.resource_group, args.vm_name)
        except Exception as exc:
            print(f"[warn] post-target health failed: {exc}")
        return 0

    if not args.skip_patch:
        patch_scraper(args.resource_group, args.vm_name)
    for fn, kwargs in (
        (verify_scraper, {}),
        (db_snapshot, {"label": "before"}),
    ):
        try:
            fn(args.resource_group, args.vm_name, **kwargs)
        except Exception as exc:
            print(f"[warn] pre-smoke check failed: {exc}")
    run_smoke(
        args.resource_group,
        args.vm_name,
        max_companies=args.max_companies,
        years_back=args.years_back,
    )
    for fn, kwargs in (
        (db_snapshot, {"label": "after"}),
        (latest_runs, {}),
        (health, {}),
    ):
        try:
            fn(args.resource_group, args.vm_name, **kwargs)
        except Exception as exc:
            print(f"[warn] post-smoke check failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
