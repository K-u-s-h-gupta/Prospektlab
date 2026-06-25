"""IPO intelligence service — orchestrates fetch, parse, score, and storage."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from finagent.ingestion.drhp_parser import parse_drhp_markdown
from finagent.ingestion.ipo_score_engine import compute_ipo_score, compute_peer_valuation
from finagent.ingestion.mineru_transformer import document_to_markdown
from finagent.ipo.store import IpoStore, get_ipo_store
from finagent.tools.data.ipo_cover_parser import parse_ipo_cover
from finagent.tools.data.ipo_enricher import enrich_filing, is_recently_listed
from finagent.tools.data.ipowatch_scraper import build_enrichment_map, fetch_ipowatch_data
from finagent.tools.data.nse_ipo_scraper import (
    build_nse_enrichment_map,
    fetch_nse_ipo_data,
    NseIpoRecord,
)
from finagent.tools.data.ipo_fetcher import (
    IpoFilingRecord,
    discover_new_filings,
    download_drhp,
    load_cached_pdf,
    run_daily_watcher,
    slugify_company,
)

logger = logging.getLogger("finagent.ipo.service")

_DOC_STAGE_RANK = {"drhp": 1, "rhp": 2, "prospectus": 3}


def _doc_stage_rank(value: Any) -> int:
    return _DOC_STAGE_RANK.get(str(value or "drhp").lower(), 1)


class IpoService:
    def __init__(self, store: IpoStore | None = None):
        self.store = store or get_ipo_store()

    async def ensure_seed_data(self) -> None:
        # Radar is populated only from the live SEBI pipeline.
        return

    async def run_watcher(self, *, download: bool = True, cover_parse: bool = True) -> dict[str, Any]:
        # Limit DRHP to the top 3 most recent filings so only the freshest upcoming IPOs appear.
        result = await run_daily_watcher(download=download, drhp_limit=3)

        # Always refresh upcoming bucket from SEBI so stale DRHPs don't linger.
        existing_upcoming = await self.store.list_filings(status="upcoming")
        for stale in existing_upcoming:
            await self.store.delete_filing(stale.get("slug", ""))

        # Deduplicate scraped records per slug — keep highest document stage rank.
        latest_by_slug: dict[str, IpoFilingRecord] = {}
        for raw in result.get("records", []):
            record = IpoFilingRecord(**{k: raw[k] for k in raw if k in IpoFilingRecord.__dataclass_fields__})
            existing_record = latest_by_slug.get(record.slug)
            if not existing_record:
                latest_by_slug[record.slug] = record
                continue
            existing_key = (_doc_stage_rank(existing_record.doc_type), existing_record.filing_date or "")
            next_key = (_doc_stage_rank(record.doc_type), record.filing_date or "")
            if next_key >= existing_key:
                latest_by_slug[record.slug] = record

        # Also collect per-slug prospectus dates so RHP-only records can check
        # whether a prospectus exists for the same company (better listed detection).
        prospectus_dates: dict[str, str] = {}
        for raw in result.get("records", []):
            if raw.get("doc_type") == "prospectus" and raw.get("filing_date"):
                prospectus_dates[raw["slug"]] = raw["filing_date"]

        for record in latest_by_slug.values():
            existing = await self.store.get_filing(record.slug) or {}

            # Build base payload merging existing stored data with fresh SEBI data.
            payload: dict[str, Any] = {
                **existing,
                "slug": record.slug,
                "company_name": record.company_name,
                "doc_type": record.doc_type,
                "filing_date": record.filing_date,
                "pdf_url": record.pdf_url,
                "exchange": record.exchange,
                "source": record.source,
            }
            if record.doc_type == "rhp":
                payload["rhp_filing_date"] = record.filing_date
            if record.doc_type == "prospectus":
                payload["prospectus_filing_date"] = record.filing_date
            # Cross-reference: if a prospectus was scraped for this slug, store its date.
            if record.slug in prospectus_dates and not payload.get("prospectus_filing_date"):
                payload["prospectus_filing_date"] = prospectus_dates[record.slug]

            # Run enrichment: infers status, sector, subscription/listing dates.
            enriched = enrich_filing(payload)
            await self.store.upsert_filing(enriched)

        # 1. Enrich from NSE APIs (authoritative source for dates, prices, subscription)
        await self._enrich_from_nse()

        # 2. Enrich from ipowatch.in (GMP, fresh/OFS breakdown, financials, KPIs)
        await self._enrich_from_ipowatch()

        # 3. Parse SEBI document cover pages for issue sizes not found elsewhere
        #    (sequential, live + recently listed only) — skipped on startup for speed.
        if cover_parse:
            await self._enrich_from_covers()

        return result

    async def _enrich_from_nse(self) -> None:
        """Fetch authoritative IPO data from NSE APIs.

        NSE provides:
        - Accurate subscription dates (from exchange announcements)
        - Real-time subscription times
        - Official price bands
        - NSE symbol
        """
        try:
            nse_data = await fetch_nse_ipo_data()
            all_nse = nse_data.get("current", []) + nse_data.get("upcoming", [])
        except Exception as exc:
            logger.warning("NSE enrichment skipped: %s", exc)
            return

        if not all_nse:
            logger.info("NSE returned no IPO data")
            return

        filings = await self.store.list_filings(limit=200)
        enrichment_map = build_nse_enrichment_map(all_nse, filings)

        updated_count = 0
        for filing in filings:
            slug = filing.get("slug") or ""
            extra = enrichment_map.get(slug)
            if not extra:
                continue

            updated = dict(filing)
            changed = False

            # NSE is authoritative — always update these fields
            for k in ("subscription_open", "subscription_close", "price_band_low",
                      "price_band_high", "nse_symbol", "is_sme"):
                v = extra.get(k)
                if v is not None and updated.get(k) != v:
                    updated[k] = v
                    changed = True

            # Subscription times — only if we have a value
            sub_times = extra.get("subscription_times")
            if sub_times is not None and sub_times > 0:
                updated["subscription_times"] = sub_times
                changed = True

            # Update status based on NSE data
            nse_status = extra.get("nse_status")
            if nse_status == "live" and updated.get("status") != "live":
                updated["status"] = "live"
                changed = True
            elif nse_status == "forthcoming" and updated.get("status") == "listed":
                # Don't downgrade from listed
                pass
            elif nse_status == "forthcoming" and updated.get("status") not in ("live", "listed"):
                updated["status"] = "upcoming"
                changed = True

            if changed:
                updated = enrich_filing(updated)
                await self.store.upsert_filing(updated)
                updated_count += 1

        logger.info("NSE enrichment: updated %d filings from %d NSE records",
                    updated_count, len(all_nse))

    async def _enrich_from_ipowatch(self) -> None:
        """Fetch price band, dates, fresh/OFS, GMP, financials from ipowatch.in.

        Stage 1: main listing → price band, dates, issue size, URLs
        Stage 2: individual pages → fresh/OFS, GMP, allotment/listing dates,
                 financials (revenue/PAT/assets), KPIs → saved to analysis store
        """
        try:
            ipowatch_records = await fetch_ipowatch_data(include_details=True)
        except Exception as exc:
            logger.warning("ipowatch enrichment skipped: %s", exc)
            return

        filings = await self.store.list_filings(limit=200)
        enrichment_map = build_enrichment_map(ipowatch_records, filings)

        updated_count = 0
        for filing in filings:
            slug = filing.get("slug") or ""
            extra = enrichment_map.get(slug)
            if not extra:
                continue

            # Pull out non-filing fields before merging
            financials_data = extra.pop("_financials", None)
            kpis_data = extra.pop("_kpis", None)

            updated = dict(filing)
            changed = False
            for k, v in extra.items():
                if v is None:
                    continue
                # Always overwrite these with ipowatch data (from exchange filings)
                if k in ("subscription_open", "subscription_close", "price_band_low",
                         "price_band_high", "gmp", "listing_date", "fresh_issue_cr",
                         "ofs_cr", "allotment_date", "lot_size"):
                    if updated.get(k) != v:
                        updated[k] = v
                        changed = True
                elif k == "issue_size_cr":
                    # ipowatch has the TOTAL size; our store may have just the fresh issue
                    # from the SEBI cover parser. Always use the larger value.
                    current_val = updated.get("issue_size_cr") or 0
                    if float(v) > float(current_val):
                        updated[k] = v
                        changed = True
                elif not updated.get(k):
                    updated[k] = v
                    changed = True

            if changed:
                updated = enrich_filing(updated)
                await self.store.upsert_filing(updated)
                updated_count += 1

            # Save financials + KPIs to analysis sidecar so detail page can show them
            if financials_data or kpis_data:
                existing_analysis = await self.store.get_analysis(slug) or {}
                analysis_changed = False
                if financials_data and not existing_analysis.get("financials"):
                    existing_analysis["financials"] = financials_data
                    analysis_changed = True
                if kpis_data and not existing_analysis.get("kpis"):
                    existing_analysis["kpis"] = kpis_data
                    analysis_changed = True
                if analysis_changed:
                    # Build minimal business synthesis if none exists
                    if not existing_analysis.get("business_synthesis"):
                        company_name = filing.get("company_name", "This company")
                        sector = filing.get("sector", "its sector")
                        existing_analysis["business_synthesis"] = (
                            f"{company_name} operates in {sector}. "
                            "Financial data sourced from the IPO prospectus. "
                            "Full DRHP analysis pending document processing."
                        )
                    await self.store.save_analysis(slug, existing_analysis)

        logger.info("ipowatch enrichment: updated %d filings", updated_count)

    async def _enrich_from_covers(self) -> None:
        """Fetch and parse SEBI document cover pages to extract price band, issue size,
        and subscription/listing dates.

        Strategy:
        - Processes live and upcoming filings first (price band + issue size most needed).
        - Also processes recently listed (last 30 days) to get real subscription dates.
        - Downloads are sequential with a 2-second delay to respect SEBI servers.
        - Skips filings that already have all key fields populated.
        """
        from datetime import date, timedelta
        filings = await self.store.list_filings(limit=200)
        cutoff = (date.today() - timedelta(days=30)).isoformat()

        def _needs_enrichment(f: dict[str, Any]) -> bool:
            return (
                not f.get("price_band_low")
                or not f.get("issue_size_cr")
                or not f.get("subscription_open")
            )

        # live/upcoming first, then recently listed
        live_upcoming = [f for f in filings if f.get("status") in ("live", "upcoming") and _needs_enrichment(f)]
        recent_listed = [
            f for f in filings
            if f.get("status") == "listed"
            and (f.get("listing_date") or f.get("prospectus_filing_date") or "") >= cutoff
            and _needs_enrichment(f)
        ]
        targets = live_upcoming + recent_listed

        for filing in targets:
            url = filing.get("pdf_url") or ""
            slug = filing.get("slug") or ""
            doc_type = filing.get("doc_type") or "drhp"
            if not url or not slug:
                continue
            try:
                cover = await parse_ipo_cover(url, doc_type=doc_type)
            except Exception as exc:
                logger.debug("Cover parse skipped for %s: %s", slug, exc)
                continue
            if not cover:
                continue
            updated = dict(filing)
            for k, v in cover.items():
                if v is not None and not updated.get(k):
                    updated[k] = v
            updated = enrich_filing(updated)
            await self.store.upsert_filing(updated)
            logger.info(
                "Cover enriched %s (%s): price=%s-%s size_cr=%s open=%s",
                filing.get("company_name"), doc_type,
                cover.get("price_band_low"), cover.get("price_band_high"),
                cover.get("issue_size_cr"), cover.get("subscription_open"),
            )
            await asyncio.sleep(2)

    async def pipeline_dashboard(self) -> dict[str, Any]:
        await self.ensure_seed_data()
        filings = await self.store.list_filings(limit=200)
        buckets: dict[str, list[dict[str, Any]]] = {"upcoming": [], "live": [], "listed": []}
        for row in filings:
            status = (row.get("status") or "upcoming").lower()
            if status not in buckets:
                status = "upcoming"
            # Only show listed companies from the last 60 days
            if status == "listed" and not is_recently_listed(row):
                continue
            card = self._to_card(row)
            buckets[status].append(card)
        # Sort buckets by filing date descending (most recent first)
        for key in buckets:
            buckets[key].sort(key=lambda c: c.get("filing_date") or "", reverse=True)
        return {
            "as_of": datetime.utcnow().isoformat() + "Z",
            "buckets": buckets,
            "gmp_disclaimer": (
                "Grey Market Premium (GMP) reflects informal off-exchange sentiment and is not a price guarantee. "
                "Use alongside the ProspektLab IPO Score for fundamental context."
            ),
        }

    async def get_analysis(self, slug: str, *, auto_analyze: bool = True) -> dict[str, Any] | None:
        """Get IPO analysis for detail page.
        
        If auto_analyze=True and no analysis exists, triggers PDF analysis in background.
        """
        await self.ensure_seed_data()
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        
        analysis = await self.store.get_analysis(slug)
        scores = await self.store.get_scores(slug)
        
        # Check if we have full DRHP analysis (not just basic ipowatch data)
        has_full_analysis = analysis and (
            analysis.get("management") or 
            analysis.get("strengths") or 
            analysis.get("risk_factors", {}).get("total_count", 0) > 0
        )
        
        # Auto-trigger analysis if full analysis missing and PDF URL available
        if auto_analyze and not has_full_analysis and filing.get("pdf_url"):
            logger.info("Auto-triggering analysis for %s", slug)
            try:
                result = await self.fetch_and_analyze(slug)
                analysis = result.get("analysis") or {}
                scores = result.get("scores") or {}
            except Exception as exc:
                logger.warning("Auto-analysis failed for %s: %s", slug, exc)
                # Return basic data even if analysis fails
                analysis = self._build_basic_analysis(filing)
                scores = {}
        
        # If still no analysis, build basic analysis from available data
        if not analysis:
            analysis = self._build_basic_analysis(filing)
        
        if not scores:
            scores = filing.get("scores") or {}
            if filing.get("composite_score"):
                scores = {
                    "composite_score": filing["composite_score"],
                    **{k: filing.get("scores", {}).get(k) for k in (
                        "business_quality", "valuation_fairness", "management_credibility",
                        "financial_health", "risk_profile",
                    )},
                }
        
        return {
            "filing": filing,
            "analysis": analysis or {},
            "scores": scores,
            "lifecycle": self._build_lifecycle(filing),
            "peer_valuation": (analysis or {}).get("peer_valuation") or {},
        }
    
    def _build_basic_analysis(self, filing: dict[str, Any]) -> dict[str, Any]:
        """Build basic analysis from filing metadata when full DRHP parse not available."""
        company_name = filing.get("company_name", "This company")
        sector = filing.get("sector", "its sector")
        doc_type = filing.get("doc_type", "DRHP").upper()
        
        # Use any financials/KPIs from ipowatch if available
        analysis: dict[str, Any] = {}
        
        # Basic business synthesis
        analysis["business_synthesis"] = (
            f"{company_name} operates in the {sector} sector. "
            f"The company has filed its {doc_type} with SEBI. "
            f"Detailed analysis will be available once the document is processed."
        )
        
        # Objects of issue from filing metadata
        objects: dict[str, Any] = {
            "fresh_issue_cr": filing.get("fresh_issue_cr"),
            "ofs_cr": filing.get("ofs_cr"),
            "total_issue_cr": filing.get("issue_size_cr"),
            "utilization": [],
            "flags": [],
        }
        if objects["fresh_issue_cr"] and objects["ofs_cr"]:
            total = objects["fresh_issue_cr"] + objects["ofs_cr"]
            if total > 0:
                objects["ofs_pct"] = round(100.0 * objects["ofs_cr"] / total, 1)
                if objects["ofs_pct"] >= 60:
                    objects["flags"].append("high_ofs_exit_signal")
        analysis["objects_of_issue"] = objects
        
        # Empty placeholders for sections that need DRHP parsing
        analysis["risk_factors"] = {"total_count": 0, "by_category": {}, "top_risks": []}
        analysis["promoters"] = {"promoters": [], "litigation_count": 0}
        analysis["management"] = []
        analysis["peers"] = []
        analysis["strengths"] = []
        analysis["strategies"] = []
        analysis["financials"] = filing.get("_financials") or {"years": [], "metrics": {}}
        analysis["kpis"] = filing.get("_kpis") or {}
        
        return analysis

    async def get_post_listing(self, slug: str) -> dict[str, Any] | None:
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        tracking = await self.store.get_post_listing(slug)
        if not tracking:
            return None
        return {"filing": filing, "tracking": tracking}

    async def fetch_and_analyze(self, slug: str, *, pdf_path: str | None = None) -> dict[str, Any]:
        filing = await self.store.get_filing(slug)
        if not filing and not pdf_path:
            raise ValueError(f"Unknown IPO slug: {slug}")

        path = pdf_path or load_cached_pdf(slug)
        if not path:
            record = IpoFilingRecord(
                company_name=filing.get("company_name", slug),
                slug=slug,
                doc_type=filing.get("doc_type", "drhp"),
                filing_date=filing.get("filing_date") or date.today().isoformat(),
                pdf_url=filing.get("pdf_url") or "",
                source=filing.get("source") or "manual",
            )
            if record.pdf_url:
                record = await download_drhp(record)
                path = record.local_path

        if not path:
            raise ValueError(f"No DRHP PDF available for {slug}")

        pdf_bytes = Path(path).read_bytes()
        doc = await document_to_markdown(pdf_bytes, Path(path).name)
        parsed = parse_drhp_markdown(doc.markdown)
        ipo_pe = None
        peer_valuation = compute_peer_valuation(parsed.get("peers") or [], ipo_pe=ipo_pe)
        scores = compute_ipo_score(parsed, peer_valuation=peer_valuation)
        parsed["peer_valuation"] = peer_valuation

        await self.store.save_analysis(slug, parsed)
        await self.store.save_scores(slug, scores)
        return {"slug": slug, "analysis": parsed, "scores": scores}

    async def search_drhp(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return await self.store.search(query, limit=limit)

    async def portfolio_ipo_links(self, symbols: list[str]) -> list[dict[str, Any]]:
        await self.ensure_seed_data()
        return await self.store.portfolio_links(symbols)

    async def discover(self) -> list[dict[str, Any]]:
        records = await discover_new_filings()
        return [record.__dict__ for record in records]

    def _to_card(self, row: dict[str, Any]) -> dict[str, Any]:
        fresh = row.get("fresh_issue_cr")
        ofs = row.get("ofs_cr")
        total = (fresh or 0) + (ofs or 0)
        ofs_pct = round(100.0 * (ofs or 0) / total, 1) if total else None
        return {
            "slug": row.get("slug"),
            "company_name": row.get("company_name"),
            "sector": row.get("sector"),
            "exchange": row.get("exchange"),
            "status": row.get("status"),
            "doc_type": row.get("doc_type"),
            "filing_date": row.get("filing_date"),
            "rhp_filing_date": row.get("rhp_filing_date"),
            "prospectus_filing_date": row.get("prospectus_filing_date"),
            "subscription_open": row.get("subscription_open"),
            "subscription_close": row.get("subscription_close"),
            "pdf_url": row.get("pdf_url"),
            "issue_size_cr": row.get("issue_size_cr"),
            "fresh_issue_cr": fresh,
            "ofs_cr": ofs,
            "ofs_pct": ofs_pct,
            "price_band": {
                "low": row.get("price_band_low"),
                "high": row.get("price_band_high"),
            },
            "composite_score": row.get("composite_score"),
            "gmp": row.get("gmp"),
            "lot_size": row.get("lot_size"),
            "subscription_status": row.get("subscription_status"),
            "subscription_times": row.get("subscription_times"),
            "nse_symbol": row.get("nse_symbol"),
            "is_sme": row.get("is_sme"),
            "listing_date": row.get("listing_date"),
            "allotment_date": row.get("allotment_date"),
        }

    def _build_lifecycle(self, filing: dict[str, Any]) -> dict[str, Any]:
        doc_type = str(filing.get("doc_type") or "drhp").lower()
        status = str(filing.get("status") or "upcoming").lower()
        has_rhp = doc_type in {"rhp", "prospectus"} or bool(filing.get("rhp_filing_date"))
        has_prospectus = doc_type == "prospectus" or bool(filing.get("prospectus_filing_date"))
        is_open = status == "live" or bool(filing.get("subscription_open"))
        is_listed = status == "listed" or bool(filing.get("listing_date"))

        def stage_state(done: bool, active: bool = False) -> str:
            if active:
                return "current"
            return "done" if done else "pending"

        stages = [
            {
                "key": "drhp",
                "label": "DRHP",
                "description": "Draft Red Herring Prospectus",
                "state": stage_state(True, doc_type == "drhp" and not is_open and not is_listed),
                "date": filing.get("filing_date"),
                "pdf_url": filing.get("pdf_url") if doc_type == "drhp" else None,
            },
            {
                "key": "rhp",
                "label": "RHP Approved",
                "description": "Red Herring Prospectus",
                "state": stage_state(has_rhp, doc_type == "rhp" and not is_open and not is_listed),
                "date": filing.get("rhp_filing_date") or (filing.get("filing_date") if has_rhp else None),
                "pdf_url": filing.get("pdf_url") if doc_type == "rhp" else None,
            },
            {
                "key": "ipo_open",
                "label": "IPO Open",
                "description": "Subscription window",
                "state": stage_state(is_open or is_listed, status == "live"),
                "date": filing.get("subscription_open"),
                "end_date": filing.get("subscription_close"),
            },
            {
                "key": "listed",
                "label": "Listed",
                "description": "Exchange listing",
                "state": stage_state(is_listed, status == "listed"),
                "date": filing.get("listing_date"),
            },
        ]
        if has_prospectus:
            stages[1]["description"] = "RHP / final prospectus available"
        return {
            "current_doc_type": doc_type,
            "source": filing.get("source") or "seed",
            "latest_document_url": filing.get("pdf_url"),
            "latest_document_date": filing.get("filing_date"),
            "stages": stages,
        }



_service: IpoService | None = None


def get_ipo_service() -> IpoService:
    global _service
    if _service is None:
        _service = IpoService()
    return _service
