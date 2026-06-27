"""IPO structured data store (Supabase with local JSON fallback).

Dual storage:
- Local JSON files (always written)
- Supabase (when SUPABASE_URL + SUPABASE_KEY configured)

Local paths:
- finagent_data/ipo/filings.json — all filing records
- finagent_data/ipo/details/{slug}/analysis.json — DRHP analysis
- finagent_data/ipo/details/{slug}/scores.json — scoring data
- finagent_data/ipo/details/{slug}/post_listing.json — tracking data

Document version management:
- When a filing is upserted with a newer/higher doc_type (prospectus > rhp > drhp),
  the existing analysis sidecar is deleted so re-analysis is triggered automatically.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from finagent.paths import finagent_data_path, finagent_home

logger = logging.getLogger("finagent.ipo.store")

_LOCAL_PATH = finagent_data_path("ipo", "filings.json")

# Document type priority for version management (higher = newer/more complete)
_DOC_TYPE_PRIORITY: dict[str, int] = {"drhp": 1, "rhp": 2, "prospectus": 3}


def _supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


class IpoStore:
    async def list_filings(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        rows = await self._load_all()
        if status:
            rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
        return rows[:limit]

    async def get_filing(self, slug: str) -> dict[str, Any] | None:
        slug = slug.strip().lower()
        for row in await self._load_all():
            if (row.get("slug") or "").lower() == slug:
                return row
        return None

    async def upsert_filing(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self._load_all()
        slug = (payload.get("slug") or "").lower()
        updated = False
        # Add timestamps
        now = datetime.now(timezone.utc).isoformat()
        if "created_at" not in payload:
            payload["created_at"] = now
        payload["updated_at"] = now
        
        doc_upgraded = False
        for idx, row in enumerate(rows):
            if (row.get("slug") or "").lower() == slug:
                # Detect document version upgrade (e.g. DRHP → RHP → Prospectus)
                old_doc_priority = _DOC_TYPE_PRIORITY.get(str(row.get("doc_type") or "drhp").lower(), 1)
                new_doc_priority = _DOC_TYPE_PRIORITY.get(str(payload.get("doc_type") or "drhp").lower(), 1)
                if new_doc_priority > old_doc_priority:
                    doc_upgraded = True
                    logger.info(
                        "[DOC-UPGRADE] %s: %s → %s — analysis cache will be invalidated",
                        slug,
                        row.get("doc_type", "drhp"),
                        payload.get("doc_type", "drhp"),
                    )
                rows[idx] = {**row, **payload, "slug": slug}
                updated = True
                break
        if not updated:
            rows.append({**payload, "slug": slug})
        await self._save_all(rows)
        if _supabase_configured():
            await self._upsert_supabase("ipo_filings", payload, match={"slug": slug})
        
        # Invalidate stale analysis when a newer document version arrives
        if doc_upgraded:
            await self._invalidate_analysis(slug)
        
        return payload

    async def _invalidate_analysis(self, slug: str) -> None:
        """Delete analysis and scores sidecars so the detail page triggers fresh re-analysis."""
        for kind in ("analysis", "scores"):
            path = await self._sidecar_path(slug, kind)
            if path.exists():
                try:
                    path.unlink()
                    logger.info("[DOC-UPGRADE] Deleted stale %s for %s — will re-parse on next access", kind, slug)
                except Exception as exc:
                    logger.warning("[DOC-UPGRADE] Could not delete %s for %s: %s", kind, slug, exc)
        # Also clear from Supabase if configured
        if _supabase_configured():
            try:
                from finagent.gateway.supabase_client import get_headers, _supabase_async_client
                headers = get_headers()
                base_url = os.environ["SUPABASE_URL"].rstrip("/")
                async with _supabase_async_client() as client:
                    for table in ("ipo_analyses", "ipo_scores"):
                        url = f"{base_url}/rest/v1/{table}?slug=eq.{slug}"
                        await client.delete(url, headers=headers)
            except Exception as exc:
                logger.debug("Supabase analysis invalidation failed for %s: %s", slug, exc)

    async def delete_filing(self, slug: str) -> None:
        slug = slug.strip().lower()
        rows = await self._load_all()
        rows = [r for r in rows if (r.get("slug") or "").lower() != slug]
        await self._save_all(rows)
        if _supabase_configured():
            try:
                from finagent.gateway.supabase_client import get_headers, _supabase_async_client
                params = f"slug=eq.{slug}"
                url = f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/ipo_filings?{params}"
                async with _supabase_async_client() as client:
                    await client.delete(url, headers=get_headers())
            except Exception as exc:
                logger.debug("Supabase IPO delete skipped/failed: %s", exc)

    async def save_analysis(self, slug: str, analysis: dict[str, Any]) -> None:
        data = {"slug": slug, "parsed_sections": analysis}
        await self._save_sidecar(slug, "analysis", data)
        if _supabase_configured():
            await self._upsert_supabase("ipo_analyses", {"slug": slug, "parsed_sections": analysis}, match={"slug": slug})

    async def get_analysis(self, slug: str) -> dict[str, Any] | None:
        data = await self._load_sidecar(slug, "analysis")
        return data.get("parsed_sections") if data else None

    async def save_scores(self, slug: str, scores: dict[str, Any]) -> None:
        await self._save_sidecar(slug, "scores", scores)
        rows = await self._load_all()
        for idx, row in enumerate(rows):
            if (row.get("slug") or "").lower() == slug.lower():
                rows[idx]["composite_score"] = scores.get("composite_score")
                rows[idx]["scores"] = scores
                break
        await self._save_all(rows)
        if _supabase_configured():
            await self._upsert_supabase("ipo_scores", {"slug": slug, **scores}, match={"slug": slug})

    async def get_scores(self, slug: str) -> dict[str, Any] | None:
        return await self._load_sidecar(slug, "scores")

    async def get_post_listing(self, slug: str) -> dict[str, Any] | None:
        return await self._load_sidecar(slug, "post_listing")

    async def save_post_listing(self, slug: str, tracking: dict[str, Any]) -> None:
        await self._save_sidecar(slug, "post_listing", tracking)
        if _supabase_configured():
            await self._upsert_supabase("ipo_post_listing", {"slug": slug, **tracking}, match={"slug": slug})

    async def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        q = query.lower().strip()
        hits: list[dict[str, Any]] = []
        for row in await self._load_all():
            hay = f"{row.get('company_name', '')} {row.get('sector', '')} {row.get('slug', '')}".lower()
            if q in hay:
                hits.append(row)
        return hits[:limit]

    async def portfolio_links(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Map portfolio symbols to IPO tracking pages for recently listed holdings."""
        sym_set = {s.strip().upper() for s in symbols if s and s.strip()}
        links: list[dict[str, Any]] = []
        for sym in sym_set:
            # Search filings by exchange symbol stored in metadata
            for filing in await self._load_all():
                if (filing.get("exchange_symbol") or "").upper() == sym:
                    slug = filing.get("slug")
                    if slug:
                        links.append({
                            "symbol": sym,
                            "slug": slug,
                            "company_name": filing.get("company_name"),
                            "tracking_url": f"/ipo/{slug}/tracking",
                            "analysis_url": f"/ipo/{slug}",
                        })
                    break
        return links

    async def clear_all(self) -> dict[str, Any]:
        """Clear ALL IPO data from both local storage and Supabase.
        
        This is a destructive operation that:
        1. Deletes all local filing data
        2. Removes all sidecar files (analyses, scores, tracking)
        3. Clears cached PDFs
        4. Truncates Supabase tables if configured
        
        Returns:
            Summary of deleted items
        """
        summary = {
            "filings_deleted": 0,
            "sidecars_deleted": 0,
            "pdfs_deleted": 0,
            "supabase_cleared": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # 1. Count and clear filings
        filings = await self._load_all()
        summary["filings_deleted"] = len(filings)
        
        # 2. Clear local JSON
        if _LOCAL_PATH.exists():
            _LOCAL_PATH.write_text("[]", encoding="utf-8")
            logger.info("Cleared local filings.json (%d records)", summary["filings_deleted"])
        
        # 3. Remove sidecar directories
        details_dir = finagent_home() / "ipo" / "details"
        if details_dir.exists():
            try:
                dir_count = sum(1 for _ in details_dir.iterdir() if _.is_dir())
                shutil.rmtree(details_dir)
                summary["sidecars_deleted"] = dir_count
                logger.info("Removed %d sidecar directories", dir_count)
            except Exception as exc:
                logger.warning("Failed to remove sidecar directories: %s", exc)
        
        # 4. Remove cached PDFs
        drhp_cache = finagent_home() / "drhp_cache"
        if drhp_cache.exists():
            try:
                pdf_count = sum(1 for _ in drhp_cache.rglob("*.pdf"))
                shutil.rmtree(drhp_cache)
                summary["pdfs_deleted"] = pdf_count
                logger.info("Removed %d cached PDFs", pdf_count)
            except Exception as exc:
                logger.warning("Failed to remove PDF cache: %s", exc)
        
        # 5. Clear Supabase tables
        if _supabase_configured():
            try:
                await self._clear_supabase_tables()
                summary["supabase_cleared"] = True
                logger.info("Cleared Supabase IPO tables")
            except Exception as exc:
                logger.warning("Failed to clear Supabase tables: %s", exc)
        
        logger.info("IPO data cleared: %s", summary)
        return summary
    
    async def _clear_supabase_tables(self) -> None:
        """Clear all IPO-related Supabase tables."""
        try:
            from finagent.gateway.supabase_client import get_headers, _supabase_async_client
            
            headers = get_headers()
            base_url = os.environ["SUPABASE_URL"].rstrip("/")
            
            # Tables to clear (in order due to FK constraints)
            tables = ["ipo_post_listing", "ipo_scores", "ipo_analyses", "ipo_filings"]
            
            async with _supabase_async_client() as client:
                for table in tables:
                    # Delete all rows
                    url = f"{base_url}/rest/v1/{table}?id=gt.00000000-0000-0000-0000-000000000000"
                    await client.delete(url, headers=headers)
                    logger.debug("Cleared Supabase table: %s", table)
        except Exception as exc:
            logger.warning("Supabase clear failed: %s", exc)
            raise

    async def _load_all(self) -> list[dict[str, Any]]:
        if _LOCAL_PATH.exists():
            try:
                return json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed reading local IPO store: %s", exc)
        return []

    async def _save_all(self, rows: list[dict[str, Any]]) -> None:
        _LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOCAL_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    async def _sidecar_path(self, slug: str, kind: str):
        return finagent_data_path("ipo", "details", slug, f"{kind}.json")

    async def _save_sidecar(self, slug: str, kind: str, data: dict[str, Any]) -> None:
        path = await self._sidecar_path(slug, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def _load_sidecar(self, slug: str, kind: str) -> dict[str, Any] | None:
        path = await self._sidecar_path(slug, kind)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    async def _upsert_supabase(self, table: str, payload: dict[str, Any], *, match: dict[str, Any]) -> None:
        try:
            from finagent.gateway.supabase_client import get_headers, _supabase_async_client

            headers = get_headers()
            params = "&".join(f"{k}=eq.{v}" for k, v in match.items())
            url = f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{table}?{params}"
            async with _supabase_async_client() as client:
                existing = await client.get(url, headers={**headers, "Accept": "application/json"})
                if existing.status_code == 200 and existing.json():
                    await client.patch(url, headers=headers, json=payload)
                else:
                    await client.post(
                        f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{table}",
                        headers=headers,
                        json=payload,
                    )
        except Exception as exc:
            logger.debug("Supabase IPO upsert skipped/failed: %s", exc)


_store: IpoStore | None = None


def get_ipo_store() -> IpoStore:
    global _store
    if _store is None:
        _store = IpoStore()
    return _store
