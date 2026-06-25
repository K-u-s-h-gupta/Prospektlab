"""IPO structured data store (Supabase with local JSON fallback)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.ipo.store")

_LOCAL_PATH = finagent_data_path("ipo", "filings.json")


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
        for idx, row in enumerate(rows):
            if (row.get("slug") or "").lower() == slug:
                rows[idx] = {**row, **payload, "slug": slug}
                updated = True
                break
        if not updated:
            rows.append({**payload, "slug": slug})
        await self._save_all(rows)
        if _supabase_configured():
            await self._upsert_supabase("ipo_filings", payload, match={"slug": slug})
        return payload

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
