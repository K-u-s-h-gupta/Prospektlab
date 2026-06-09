"""Estimate Azure Document Intelligence usage from local logs and Supabase rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from finagent.ikg.db import connect_postgres, get_database_url


def _read_usage_logs(log_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(log_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("azure_di_usage_*.jsonl")):
        with file_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def _sum_db_pages(database_url: str | None = None) -> dict[str, int]:
    db_url = get_database_url(database_url)
    if not db_url:
        return {}
    queries = {
        "annual_reports_raw": "select coalesce(sum(page_count), 0)::bigint as pages from annual_reports_raw where extraction_status in ('ok', 'targeted')",
        "corporate_filings_raw": "select coalesce(sum(attachment_page_count), 0)::bigint as pages from corporate_filings_raw where attachment_extraction_status = 'ok'",
        "concall_transcripts_raw": "select coalesce(sum(attachment_page_count), 0)::bigint as pages from concall_transcripts_raw where extraction_status = 'ok'",
    }
    out: dict[str, int] = {}
    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            for name, sql in queries.items():
                try:
                    cur.execute(sql)
                    row = cur.fetchone() or {}
                    out[name] = int(row.get("pages") or 0)
                except Exception:
                    conn.rollback()
                    out[name] = 0
    return out


def estimate_di_cost(
    *,
    log_dir: str | Path = "pipeline_logs",
    price_per_1000_pages: float = 10.0,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Estimate DI cost. Default price is a rough Layout-rate placeholder."""
    usage = _read_usage_logs(log_dir)
    logged_pages = sum(int(row.get("pages_billed_estimate") or 0) for row in usage if row.get("success", True))
    by_model: dict[str, int] = {}
    for row in usage:
        model = str(row.get("model_id") or "unknown")
        by_model[model] = by_model.get(model, 0) + int(row.get("pages_billed_estimate") or 0)

    db_pages = _sum_db_pages(database_url)
    db_total = sum(db_pages.values())
    pages = logged_pages or db_total
    return {
        "logged_usage_calls": len(usage),
        "logged_pages": logged_pages,
        "db_extracted_pages_estimate": db_total,
        "db_pages_by_table": db_pages,
        "pages_used_for_cost_estimate": pages,
        "price_per_1000_pages": price_per_1000_pages,
        "estimated_cost": round((pages / 1000.0) * price_per_1000_pages, 2),
        "pages_by_model_from_logs": by_model,
        "note": "Use Azure Portal Cost Management for the exact bill; this is a pipeline-side estimate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate Azure DI cost from logs/Supabase")
    parser.add_argument("--log-dir", default="pipeline_logs")
    parser.add_argument("--price-per-1000-pages", type=float, default=10.0)
    args = parser.parse_args()
    print(json.dumps(estimate_di_cost(log_dir=args.log_dir, price_per_1000_pages=args.price_per_1000_pages), indent=2))


if __name__ == "__main__":
    main()
