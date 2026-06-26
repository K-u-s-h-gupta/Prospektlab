"""IPO intelligence service — orchestrates fetch, parse, score, and storage.

Enhanced IPO tracking system with:
- PyMuPDF as the primary IPO document parser
- Heuristic cleanup and section extraction for DRHP/RHP filings
- BSE + NSE dual exchange integration
- Configurable polling and batch processing
- Real-time lifecycle tracking
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finagent.ingestion.drhp_parser import parse_drhp_markdown, parse_drhp_markdown_parallel
from finagent.ingestion.ipo_score_engine import compute_ipo_score, compute_peer_valuation
from finagent.ipo.store import IpoStore, get_ipo_store
from finagent.tools.data.ipo_cover_parser import parse_ipo_cover
from finagent.tools.data.ipo_enricher import enrich_filing, is_recently_listed, RECENTLY_LISTED_DAYS
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

# Configuration
IPO_POLL_INTERVAL_HOURS = int(os.getenv("IPO_POLL_INTERVAL_HOURS", "4"))
IPO_BATCH_SIZE = int(os.getenv("IPO_BATCH_SIZE", "5"))
IPO_DRHP_LIMIT = int(os.getenv("IPO_DRHP_LIMIT", "10"))
IPO_BACKGROUND_WORKERS = int(os.getenv("IPO_BACKGROUND_WORKERS", "1"))
IPO_ANALYSIS_VERSION = "pymupdf-v2"

_DOC_STAGE_RANK = {"drhp": 1, "rhp": 2, "prospectus": 3}


def _doc_stage_rank(value: Any) -> int:
    return _DOC_STAGE_RANK.get(str(value or "drhp").lower(), 1)


class AnalysisStatus:
    """Status of an IPO analysis job."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IpoService:
    """Central orchestrator for IPO tracking system.
    
    Responsibilities:
    - Fetch IPO data from SEBI, NSE, BSE, ipowatch
    - Process documents through the PyMuPDF IPO extraction pipeline
    - Score and analyze filings
    - Manage lifecycle tracking
    - Provide data for frontend
    - Background analysis queue for pre-processing
    """
    
    def __init__(self, store: IpoStore | None = None):
        self.store = store or get_ipo_store()
        self._extraction_stats = {
            "pymupdf_success": 0,
            "extraction_failures": 0,
        }
        # Analysis queue for background processing
        self._analysis_queue: asyncio.PriorityQueue[tuple[int, int, str]] = asyncio.PriorityQueue()
        self._analysis_status: dict[str, dict[str, Any]] = {}  # slug -> {status, started_at, error}
        self._workers_started = False
        self._worker_tasks: list[asyncio.Task] = []
        self._queue_sequence = 0
    
    async def start_background_workers(self) -> None:
        """Start background workers for pre-processing IPO analyses."""
        if self._workers_started:
            return
        
        self._workers_started = True
        for i in range(IPO_BACKGROUND_WORKERS):
            task = asyncio.create_task(self._analysis_worker(i))
            self._worker_tasks.append(task)
        
        logger.info("Started %d background analysis workers", IPO_BACKGROUND_WORKERS)
    
    async def stop_background_workers(self) -> None:
        """Stop all background workers."""
        for task in self._worker_tasks:
            task.cancel()
        self._worker_tasks = []
        self._workers_started = False
        logger.info("Stopped background analysis workers")

    def _analysis_has_required_content(self, analysis: dict[str, Any] | None) -> bool:
        return bool(
            analysis and (
                analysis.get("management") or
                analysis.get("strengths") or
                analysis.get("risk_factors", {}).get("total_count", 0) > 0
            )
        )

    def _analysis_needs_refresh(self, analysis: dict[str, Any] | None) -> bool:
        if not analysis:
            return True
        if analysis.get("_parser_version") != IPO_ANALYSIS_VERSION:
            return True
        if isinstance(analysis.get("kpis"), list):
            return True
        business = str(analysis.get("business_synthesis") or "")
        if "................................" in business:
            return True
        return False

    def _financials_look_valid(self, financials: dict[str, Any]) -> bool:
        years = [str(year or "").strip() for year in (financials.get("years") or []) if str(year or "").strip()]
        metrics = financials.get("metrics") or {}
        if len(set(years)) < 2:
            return False
        revenue_values = [value for value in (metrics.get("revenue") or []) if isinstance(value, (int, float))]
        if len(revenue_values) >= 2:
            min_revenue = min(abs(float(value)) for value in revenue_values if value is not None)
            max_revenue = max(abs(float(value)) for value in revenue_values if value is not None)
            if min_revenue > 0 and max_revenue / min_revenue > 15:
                return False
        return any(any(value is not None for value in values) for values in metrics.values())

    def _build_business_synthesis_copy(self, analysis: dict[str, Any]) -> str:
        paragraphs = [str(p).strip() for p in (analysis.get("business_overview_paragraphs") or []) if str(p).strip()]
        strengths = [str(item).strip() for item in (analysis.get("strengths") or []) if str(item).strip()]
        objects = analysis.get("objects_of_issue") or {}
        financials = analysis.get("financials") or {}

        parts: list[str] = []
        if paragraphs:
            parts.extend(paragraphs[:2])
        elif strengths:
            parts.append(strengths[0])

        trends = financials.get("trends") or {}
        rev_cagr = trends.get("revenue_cagr_pct")
        pat_cagr = trends.get("pat_cagr_pct")
        growth_bits: list[str] = []
        if isinstance(rev_cagr, (int, float)):
            growth_bits.append(f"revenue CAGR of {rev_cagr}%")
        if isinstance(pat_cagr, (int, float)):
            growth_bits.append(f"PAT CAGR of {pat_cagr}%")
        if growth_bits:
            parts.append("The restated financials indicate " + " and ".join(growth_bits) + ".")

        utilization = objects.get("utilization") or []
        if utilization:
            labels = [item.get("label") for item in utilization if item.get("label")]
            if labels:
                parts.append(f"The fresh-issue proceeds are primarily intended for {', '.join(labels[:3])}.")

        if strengths and not paragraphs:
            first_strength = strengths[0]
            if not any(first_strength in part for part in parts):
                parts.append(f"A key strength highlighted in the filing is: {first_strength}")

        return " ".join(part.strip() for part in parts if part).strip()
    
    async def _analysis_worker(self, worker_id: int) -> None:
        """Background worker that processes analysis queue."""
        logger.info("Analysis worker %d started", worker_id)
        
        while True:
            try:
                # Wait for item from queue
                _, _, slug = await self._analysis_queue.get()
                
                # Check if already analyzed or in progress
                status = self._analysis_status.get(slug, {})
                if status.get("status") in (AnalysisStatus.COMPLETED, AnalysisStatus.IN_PROGRESS):
                    self._analysis_queue.task_done()
                    continue
                
                # Mark as in progress
                self._analysis_status[slug] = {
                    "status": AnalysisStatus.IN_PROGRESS,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "worker": worker_id,
                }
                
                logger.info("[Worker %d] Analyzing: %s", worker_id, slug)
                
                try:
                    await self.fetch_and_analyze(slug)
                    self._analysis_status[slug] = {
                        "status": AnalysisStatus.COMPLETED,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    logger.info("[Worker %d] Completed: %s", worker_id, slug)
                except Exception as exc:
                    self._analysis_status[slug] = {
                        "status": AnalysisStatus.FAILED,
                        "error": str(exc),
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    logger.warning("[Worker %d] Failed %s: %s", worker_id, slug, exc)
                
                self._analysis_queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("Analysis worker %d cancelled", worker_id)
                break
            except Exception as exc:
                logger.error("Analysis worker %d error: %s", worker_id, exc)
                await asyncio.sleep(5)  # Prevent tight error loop
    
    async def queue_analysis(self, slug: str, priority: bool = False) -> dict[str, Any]:
        """Queue an IPO for background analysis.
        
        Args:
            slug: IPO slug to analyze
            priority: If True, move ahead in the background queue
        
        Returns:
            Status dict with queue position or result
        """
        # Check if already analyzed
        analysis = await self.store.get_analysis(slug)
        if self._analysis_has_required_content(analysis) and not self._analysis_needs_refresh(analysis):
            return {
                "status": AnalysisStatus.COMPLETED,
                "message": "Analysis already exists",
            }

        # Start workers on demand so the detail page can recover even if
        # startup hooks were skipped or the service singleton was re-created.
        if not self._workers_started:
            await self.start_background_workers()
        
        # Check current status
        current = self._analysis_status.get(slug, {})
        if current.get("status") == AnalysisStatus.IN_PROGRESS:
            return {
                "status": AnalysisStatus.IN_PROGRESS,
                "message": "Analysis in progress",
                "started_at": current.get("started_at"),
            }

        if current.get("status") == AnalysisStatus.PENDING:
            if priority and not current.get("priority_promoted"):
                current["priority_promoted"] = True
                self._queue_sequence += 1
                await self._analysis_queue.put((0, self._queue_sequence, slug))
                return {
                    "status": AnalysisStatus.PENDING,
                    "message": "Analysis priority updated",
                    "queue_size": self._analysis_queue.qsize(),
                }

            return {
                "status": AnalysisStatus.PENDING,
                "message": "Analysis already queued",
                "queue_size": self._analysis_queue.qsize(),
            }

        # Add to queue
        queue_priority = 0 if priority else 1
        self._analysis_status[slug] = {
            "status": AnalysisStatus.PENDING,
            "priority_promoted": priority,
        }
        self._queue_sequence += 1
        await self._analysis_queue.put((queue_priority, self._queue_sequence, slug))
        
        return {
            "status": AnalysisStatus.PENDING,
            "message": "Queued for analysis",
            "queue_size": self._analysis_queue.qsize(),
        }
    
    async def get_analysis_status(self, slug: str) -> dict[str, Any]:
        """Get current analysis status for an IPO.
        
        Returns status, whether analysis exists, and any errors.
        """
        filing = await self.store.get_filing(slug)
        if not filing:
            return {"exists": False, "status": "not_found"}
        
        analysis = await self.store.get_analysis(slug)
        scores = await self.store.get_scores(slug)

        has_full_analysis = self._analysis_has_required_content(analysis) and not self._analysis_needs_refresh(analysis)
        
        queue_status = self._analysis_status.get(slug, {})
        
        return {
            "exists": True,
            "slug": slug,
            "company_name": filing.get("company_name"),
            "has_pdf": bool(filing.get("pdf_url")),
            "has_analysis": has_full_analysis,
            "has_scores": bool(scores and scores.get("composite_score")),
            "analysis_status": queue_status.get("status") if queue_status else (
                AnalysisStatus.COMPLETED if has_full_analysis else AnalysisStatus.PENDING
            ),
            "error": queue_status.get("error"),
        }
    
    async def queue_all_pending_analyses(self) -> dict[str, Any]:
        """Queue all IPOs that need analysis for background processing.
        
        Called at startup and after watcher runs to pre-process documents.
        """
        if not self._workers_started:
            await self.start_background_workers()

        filings = await self.store.list_filings(limit=500)
        
        queued = 0
        skipped = 0
        no_pdf = 0
        
        for filing in filings:
            slug = filing.get("slug", "")
            
            # Skip if no PDF
            if not filing.get("pdf_url"):
                no_pdf += 1
                continue
            
            # Check if already analyzed
            analysis = await self.store.get_analysis(slug)
            if self._analysis_has_required_content(analysis) and not self._analysis_needs_refresh(analysis):
                skipped += 1
                continue
            
            # Check if already in queue or in progress
            status = self._analysis_status.get(slug, {})
            if status.get("status") in (AnalysisStatus.PENDING, AnalysisStatus.IN_PROGRESS):
                continue
            
            # Queue for analysis
            self._analysis_status[slug] = {
                "status": AnalysisStatus.PENDING,
                "priority_promoted": False,
            }
            self._queue_sequence += 1
            await self._analysis_queue.put((1, self._queue_sequence, slug))
            queued += 1
        
        logger.info(
            "Queued %d IPOs for analysis (skipped %d already analyzed, %d no PDF)",
            queued, skipped, no_pdf
        )
        
        return {
            "queued": queued,
            "skipped_analyzed": skipped,
            "skipped_no_pdf": no_pdf,
            "queue_size": self._analysis_queue.qsize(),
        }

    async def ensure_seed_data(self) -> None:
        """Ensure minimal seed data exists. No-op for live pipeline."""
        return

    async def clear_all_data(self) -> dict[str, Any]:
        """Clear all existing IPO data for fresh start.
        
        WARNING: This is destructive and cannot be undone.
        
        Returns:
            Summary of cleared data
        """
        logger.warning("Clearing ALL IPO data...")
        result = await self.store.clear_all()
        logger.info("IPO data cleared: %s", result)
        return result

    async def run_watcher(
        self,
        *,
        download: bool = True,
        cover_parse: bool = True,
        include_bse: bool = True,
        batch_process: bool = True,
    ) -> dict[str, Any]:
        """Run full IPO watcher pipeline.
        
        Pipeline stages:
        1. SEBI document discovery (DRHP/RHP/Prospectus)
        2. Deduplication by slug (keep highest doc stage)
        3. NSE API enrichment (authoritative dates, prices, subscription)
        4. BSE API enrichment (if enabled)
        5. ipowatch enrichment (GMP, financials, KPIs)
        6. Cover page parsing (issue sizes, dates)
        7. Batch document analysis (if enabled)
        
        Args:
            download: Download PDF documents
            cover_parse: Parse cover pages for metadata
            include_bse: Include BSE scraping
            batch_process: Run batch document analysis
        
        Returns:
            Watcher run summary
        """
        start_time = datetime.now(timezone.utc)
        result = {
            "started_at": start_time.isoformat(),
            "sebi_records": 0,
            "nse_enriched": 0,
            "bse_enriched": 0,
            "ipowatch_enriched": 0,
            "covers_parsed": 0,
            "documents_analyzed": 0,
            "errors": [],
        }
        
        try:
            # Stage 1: SEBI document discovery
            sebi_result = await run_daily_watcher(download=download, drhp_limit=IPO_DRHP_LIMIT)
            result["sebi_records"] = len(sebi_result.get("records", []))
            
            # Clear stale upcoming filings
            existing_upcoming = await self.store.list_filings(status="upcoming")
            for stale in existing_upcoming:
                await self.store.delete_filing(stale.get("slug", ""))
            
            # Stage 2: Deduplicate and store
            latest_by_slug = await self._deduplicate_filings(sebi_result.get("records", []))
            prospectus_dates = self._collect_prospectus_dates(sebi_result.get("records", []))
            
            for record in latest_by_slug.values():
                existing = await self.store.get_filing(record.slug) or {}
                payload = self._build_filing_payload(record, existing, prospectus_dates)
                enriched = enrich_filing(payload)
                await self.store.upsert_filing(enriched)
            
            # Stage 3: NSE enrichment
            try:
                nse_count = await self._enrich_from_nse()
                result["nse_enriched"] = nse_count
            except Exception as exc:
                result["errors"].append(f"NSE enrichment: {str(exc)}")
                logger.warning("NSE enrichment failed: %s", exc)
            
            # Stage 4: BSE enrichment (new)
            if include_bse:
                try:
                    bse_count = await self._enrich_from_bse()
                    result["bse_enriched"] = bse_count
                except Exception as exc:
                    result["errors"].append(f"BSE enrichment: {str(exc)}")
                    logger.warning("BSE enrichment failed: %s", exc)
            
            # Stage 5: ipowatch enrichment
            try:
                ipowatch_count = await self._enrich_from_ipowatch()
                result["ipowatch_enriched"] = ipowatch_count
            except Exception as exc:
                result["errors"].append(f"ipowatch enrichment: {str(exc)}")
                logger.warning("ipowatch enrichment failed: %s", exc)
            
            # Stage 6: Cover page parsing
            if cover_parse:
                try:
                    cover_count = await self._enrich_from_covers()
                    result["covers_parsed"] = cover_count
                except Exception as exc:
                    result["errors"].append(f"Cover parsing: {str(exc)}")
                    logger.warning("Cover parsing failed: %s", exc)
            
            # Stage 7: Batch document analysis
            if batch_process:
                try:
                    analyzed_count = await self._batch_analyze_documents()
                    result["documents_analyzed"] = analyzed_count
                except Exception as exc:
                    result["errors"].append(f"Batch analysis: {str(exc)}")
                    logger.warning("Batch analysis failed: %s", exc)
            
            # Stage 8: Queue remaining IPOs for background analysis
            try:
                queue_result = await self.queue_all_pending_analyses()
                result["queued_for_analysis"] = queue_result.get("queued", 0)
            except Exception as exc:
                result["errors"].append(f"Queue analyses: {str(exc)}")
                logger.warning("Queue analyses failed: %s", exc)
            
        except Exception as exc:
            result["errors"].append(f"Watcher error: {str(exc)}")
            logger.error("Watcher run failed: %s", exc)
        
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        result["duration_s"] = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(
            "Watcher completed: %d SEBI, %d NSE, %d BSE, %d ipowatch, %d covers, %d analyzed",
            result["sebi_records"], result["nse_enriched"], result["bse_enriched"],
            result["ipowatch_enriched"], result["covers_parsed"], result["documents_analyzed"]
        )
        
        return result

    async def _deduplicate_filings(self, records: list[dict]) -> dict[str, IpoFilingRecord]:
        """Deduplicate records by slug, keeping highest document stage."""
        latest_by_slug: dict[str, IpoFilingRecord] = {}
        
        for raw in records:
            record = IpoFilingRecord(**{k: raw[k] for k in raw if k in IpoFilingRecord.__dataclass_fields__})
            existing_record = latest_by_slug.get(record.slug)
            if not existing_record:
                latest_by_slug[record.slug] = record
                continue
            existing_key = (_doc_stage_rank(existing_record.doc_type), existing_record.filing_date or "")
            next_key = (_doc_stage_rank(record.doc_type), record.filing_date or "")
            if next_key >= existing_key:
                latest_by_slug[record.slug] = record
        
        return latest_by_slug

    def _collect_prospectus_dates(self, records: list[dict]) -> dict[str, str]:
        """Collect prospectus filing dates for cross-reference."""
        prospectus_dates: dict[str, str] = {}
        for raw in records:
            if raw.get("doc_type") == "prospectus" and raw.get("filing_date"):
                prospectus_dates[raw["slug"]] = raw["filing_date"]
        return prospectus_dates

    def _build_filing_payload(
        self,
        record: IpoFilingRecord,
        existing: dict[str, Any],
        prospectus_dates: dict[str, str],
    ) -> dict[str, Any]:
        """Build filing payload from record and existing data."""
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
        if record.slug in prospectus_dates and not payload.get("prospectus_filing_date"):
            payload["prospectus_filing_date"] = prospectus_dates[record.slug]
        return payload

    async def _enrich_from_nse(self) -> int:
        """Enrich filings from NSE APIs (authoritative source)."""
        nse_data = await fetch_nse_ipo_data()
        all_nse = nse_data.get("current", []) + nse_data.get("upcoming", [])
        
        if not all_nse:
            logger.info("NSE returned no IPO data")
            return 0
        
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
            
            # NSE is authoritative for these fields
            for k in ("subscription_open", "subscription_close", "price_band_low",
                      "price_band_high", "nse_symbol", "is_sme"):
                v = extra.get(k)
                if v is not None and updated.get(k) != v:
                    updated[k] = v
                    changed = True
            
            # Subscription times
            sub_times = extra.get("subscription_times")
            if sub_times is not None and sub_times > 0:
                updated["subscription_times"] = sub_times
                changed = True
            
            # Status update
            nse_status = extra.get("nse_status")
            if nse_status == "live" and updated.get("status") != "live":
                updated["status"] = "live"
                changed = True
            elif nse_status == "forthcoming" and updated.get("status") not in ("live", "listed"):
                updated["status"] = "upcoming"
                changed = True
            
            if changed:
                updated = enrich_filing(updated)
                await self.store.upsert_filing(updated)
                updated_count += 1
        
        logger.info("NSE enrichment: updated %d filings", updated_count)
        return updated_count

    async def _enrich_from_bse(self) -> int:
        """Enrich filings from BSE APIs."""
        try:
            from finagent.tools.data.bse_ipo_scraper import (
                fetch_bse_ipo_data,
                build_bse_enrichment_map,
            )
        except ImportError:
            logger.warning("BSE scraper not available")
            return 0
        
        bse_data = await fetch_bse_ipo_data()
        all_bse = bse_data.get("current", []) + bse_data.get("upcoming", [])
        
        if not all_bse:
            logger.info("BSE returned no IPO data")
            return 0
        
        filings = await self.store.list_filings(limit=200)
        enrichment_map = build_bse_enrichment_map(all_bse, filings)
        
        updated_count = 0
        for filing in filings:
            slug = filing.get("slug") or ""
            extra = enrichment_map.get(slug)
            if not extra:
                continue
            
            updated = dict(filing)
            changed = False
            
            # IPO data from exchange (don't override existing data if present)
            for k in ("scrip_code", "nse_symbol", "lot_size", "times_subscribed"):
                v = extra.get(k)
                if v is not None and not updated.get(k):
                    updated[k] = v
                    changed = True
            
            # Only use BSE dates if NSE didn't provide them
            for k in ("subscription_open", "subscription_close", "price_band_low", "price_band_high"):
                v = extra.get(k)
                if v is not None and not updated.get(k):
                    updated[k] = v
                    changed = True
            
            if changed:
                updated = enrich_filing(updated)
                await self.store.upsert_filing(updated)
                updated_count += 1
        
        logger.info("BSE enrichment: updated %d filings", updated_count)
        return updated_count

    async def _enrich_from_ipowatch(self) -> int:
        """Enrich filings from ipowatch.in (GMP, financials, KPIs)."""
        ipowatch_records = await fetch_ipowatch_data(include_details=True)
        filings = await self.store.list_filings(limit=200)
        enrichment_map = build_enrichment_map(ipowatch_records, filings)
        
        updated_count = 0
        for filing in filings:
            slug = filing.get("slug") or ""
            extra = enrichment_map.get(slug)
            if not extra:
                continue
            
            financials_data = extra.pop("_financials", None)
            kpis_data = extra.pop("_kpis", None)
            
            updated = dict(filing)
            changed = False
            
            for k, v in extra.items():
                if v is None:
                    continue
                if k in ("subscription_open", "subscription_close", "price_band_low",
                         "price_band_high", "gmp", "listing_date", "fresh_issue_cr",
                         "ofs_cr", "allotment_date", "lot_size"):
                    if updated.get(k) != v:
                        updated[k] = v
                        changed = True
                elif k == "issue_size_cr":
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
            
            # Save financials + KPIs to analysis
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
        return updated_count

    async def _enrich_from_covers(self) -> int:
        """Parse SEBI document cover pages for metadata."""
        filings = await self.store.list_filings(limit=200)
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        
        def _needs_enrichment(f: dict[str, Any]) -> bool:
            return (
                not f.get("price_band_low")
                or not f.get("issue_size_cr")
                or not f.get("subscription_open")
            )
        
        live_upcoming = [f for f in filings if f.get("status") in ("live", "upcoming") and _needs_enrichment(f)]
        recent_listed = [
            f for f in filings
            if f.get("status") == "listed"
            and (f.get("listing_date") or f.get("prospectus_filing_date") or "") >= cutoff
            and _needs_enrichment(f)
        ]
        targets = live_upcoming + recent_listed
        
        enriched_count = 0
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
            enriched_count += 1
            logger.debug("Cover enriched %s: price=%s-%s", slug, cover.get("price_band_low"), cover.get("price_band_high"))
            await asyncio.sleep(2)  # Respect SEBI servers
        
        return enriched_count

    async def _batch_analyze_documents(self) -> int:
        """Batch analyze documents using Docling with Azure DI fallback."""
        filings = await self.store.list_filings(limit=200)
        
        # Find filings needing analysis
        needs_analysis = []
        for f in filings:
            if not f.get("pdf_url"):
                continue
            analysis = await self.store.get_analysis(f.get("slug", ""))
            if not analysis or not analysis.get("management"):
                needs_analysis.append(f)
        
        # Batch process
        analyzed_count = 0
        for filing in needs_analysis[:IPO_BATCH_SIZE]:
            try:
                slug = filing.get("slug", "")
                logger.info("Batch analyzing: %s", slug)
                await self.fetch_and_analyze(slug)
                analyzed_count += 1
            except Exception as exc:
                logger.warning("Batch analysis failed for %s: %s", filing.get("slug"), exc)
        
        return analyzed_count

    async def pipeline_dashboard(self) -> dict[str, Any]:
        """Get pipeline dashboard data for frontend.
        
        Returns:
            Buckets (live, upcoming, listed) with IPO cards
        """
        await self.ensure_seed_data()
        filings = await self.store.list_filings(limit=200)
        buckets: dict[str, list[dict[str, Any]]] = {"upcoming": [], "live": [], "listed": []}
        
        for row in filings:
            status = (row.get("status") or "upcoming").lower()
            if status not in buckets:
                status = "upcoming"
            # Only show recently listed
            if status == "listed" and not is_recently_listed(row):
                continue
            card = self._to_card(row)
            buckets[status].append(card)
        
        # Sort by filing date descending
        for key in buckets:
            buckets[key].sort(key=lambda c: c.get("filing_date") or "", reverse=True)
        
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "buckets": buckets,
            "counts": {k: len(v) for k, v in buckets.items()},
            "gmp_disclaimer": (
                "Grey Market Premium (GMP) reflects informal off-exchange sentiment and is not a price guarantee. "
                "Use alongside the ProspektLab IPO Score for fundamental context."
            ),
        }

    async def get_analysis(self, slug: str, *, auto_analyze: bool = True) -> dict[str, Any] | None:
        """Get IPO analysis for detail page.
        
        If auto_analyze=True and no analysis exists, triggers document analysis.
        """
        await self.ensure_seed_data()
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        
        analysis = await self.store.get_analysis(slug)
        scores = await self.store.get_scores(slug)

        has_full_analysis = self._analysis_has_required_content(analysis)
        needs_refresh = self._analysis_needs_refresh(analysis)

        if auto_analyze and (not has_full_analysis or needs_refresh) and filing.get("pdf_url"):
            logger.info("Auto-triggering analysis for %s", slug)
            try:
                result = await self.fetch_and_analyze(slug)
                analysis = result.get("analysis") or {}
                scores = result.get("scores") or {}
            except Exception as exc:
                logger.warning("Auto-analysis failed for %s: %s", slug, exc)
                analysis = self._build_basic_analysis(filing)
                scores = {}
        
        if not analysis:
            analysis = self._build_basic_analysis(filing)

        analysis = self._hydrate_analysis_from_filing(analysis, filing)
        
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
        """Build basic analysis when full parse unavailable."""
        company_name = filing.get("company_name", "This company")
        sector = filing.get("sector", "its sector")
        doc_type = filing.get("doc_type", "DRHP").upper()
        
        analysis: dict[str, Any] = {}
        analysis["business_synthesis"] = (
            f"{company_name} operates in the {sector} sector. "
            f"The company has filed its {doc_type} with SEBI. "
            f"Detailed analysis will be available once the document is processed."
        )
        analysis["business_overview_paragraphs"] = [analysis["business_synthesis"]]
        
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
        
        analysis["risk_factors"] = {"total_count": 0, "by_category": {}, "top_risks": []}
        analysis["promoters"] = {"promoters": [], "litigation_count": 0}
        analysis["management"] = []
        analysis["peers"] = []
        analysis["strengths"] = []
        analysis["strategies"] = []
        analysis["financials"] = filing.get("_financials") or {"years": [], "metrics": {}}
        analysis["kpis"] = filing.get("_kpis") or {}
        analysis["kpi_rows"] = []
        analysis["objects_summary"] = self._build_objects_summary(objects)
        analysis["financial_summary"] = self._build_financial_summary(analysis["financials"], analysis["kpis"])
        analysis["valuation_summary"] = self._build_valuation_summary({}, analysis["kpis"], filing)
        analysis["risk_summary"] = self._build_risk_summary(analysis["risk_factors"])
        analysis["governance_summary"] = self._build_governance_summary(analysis["promoters"], analysis["management"], [])
        
        return analysis

    def _hydrate_analysis_from_filing(self, analysis: dict[str, Any], filing: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(analysis or {})

        objects = dict(hydrated.get("objects_of_issue") or {})
        filing_fresh_issue = filing.get("fresh_issue_cr")
        if filing_fresh_issue is not None and (
            objects.get("fresh_issue_cr") is None or
            not isinstance(objects.get("fresh_issue_cr"), (int, float)) or
            abs(float(objects.get("fresh_issue_cr") or 0) - float(filing_fresh_issue)) > max(50.0, float(filing_fresh_issue) * 0.5)
        ):
            objects["fresh_issue_cr"] = filing.get("fresh_issue_cr")
        filing_ofs = filing.get("ofs_cr")
        if filing_ofs is not None and (
            objects.get("ofs_cr") is None or
            not isinstance(objects.get("ofs_cr"), (int, float)) or
            abs(float(objects.get("ofs_cr") or 0) - float(filing_ofs)) > max(25.0, float(filing_ofs or 0) * 0.5)
        ):
            objects["ofs_cr"] = filing.get("ofs_cr")
        filing_total_issue = filing.get("issue_size_cr")
        if filing_total_issue is not None and (
            objects.get("total_issue_cr") is None or
            not isinstance(objects.get("total_issue_cr"), (int, float)) or
            abs(float(objects.get("total_issue_cr") or 0) - float(filing_total_issue)) > max(50.0, float(filing_total_issue) * 0.35)
        ):
            objects["total_issue_cr"] = filing.get("issue_size_cr")
        if objects.get("ofs_pct") is None and objects.get("fresh_issue_cr") is not None and objects.get("ofs_cr") is not None:
            total_issue = (objects.get("fresh_issue_cr") or 0) + (objects.get("ofs_cr") or 0)
            if total_issue > 0:
                objects["ofs_pct"] = round(100.0 * (objects.get("ofs_cr") or 0) / total_issue, 1)
        utilization = [item for item in (objects.get("utilization") or []) if isinstance(item.get("amount_cr"), (int, float))]
        if utilization and isinstance(objects.get("fresh_issue_cr"), (int, float)):
            utilization_total = sum(float(item.get("amount_cr") or 0) for item in utilization)
            fresh_issue_value = float(objects.get("fresh_issue_cr") or 0)
            if fresh_issue_value > 0 and utilization_total < max(5.0, fresh_issue_value * 0.1):
                utilization = []
        objects["utilization"] = utilization
        objects.setdefault("utilization", [])
        objects.setdefault("flags", [])
        hydrated["objects_of_issue"] = objects

        financials = hydrated.get("financials") or {}
        filing_financials = filing.get("_financials") or {}
        if not financials.get("metrics") and filing_financials:
            financials = filing_financials
        if financials and not self._financials_look_valid(financials):
            financials = filing_financials if filing_financials else {"years": [], "metrics": {}, "trends": {}, "flags": []}
        financials.setdefault("years", [])
        financials.setdefault("metrics", {})
        financials.setdefault("trends", {})
        financials.setdefault("flags", [])
        hydrated["financials"] = financials

        kpis = hydrated.get("kpis") or {}
        if isinstance(kpis, list):
            kpis = {}
        filing_kpis = filing.get("_kpis") or {}
        if not kpis and filing_kpis:
            kpis = dict(filing_kpis)
        hydrated["kpis"] = kpis
        hydrated["kpi_rows"] = hydrated.get("kpi_rows") or []

        if not hydrated.get("business_overview_paragraphs"):
            business = str(hydrated.get("business_synthesis") or hydrated.get("business_overview_excerpt") or "").strip()
            hydrated["business_overview_paragraphs"] = [business] if business else []

        synthesized_business = self._build_business_synthesis_copy(hydrated)
        hydrated["business_synthesis"] = synthesized_business or self._build_basic_analysis(filing)["business_synthesis"]

        peer_valuation = hydrated.get("peer_valuation") or {}
        hydrated["objects_summary"] = self._build_objects_summary(objects)
        hydrated["financial_summary"] = self._build_financial_summary(financials, kpis)
        hydrated["valuation_summary"] = self._build_valuation_summary(peer_valuation, kpis, filing)
        hydrated["risk_summary"] = self._build_risk_summary(hydrated.get("risk_factors") or {})
        hydrated["governance_summary"] = self._build_governance_summary(
            hydrated.get("promoters") or {},
            hydrated.get("management") or [],
            hydrated.get("fraud_signals") or [],
        )
        return hydrated

    def _build_objects_summary(self, objects: dict[str, Any]) -> str:
        fresh_issue = objects.get("fresh_issue_cr")
        ofs_cr = objects.get("ofs_cr")
        total_issue = objects.get("total_issue_cr")
        utilization = objects.get("utilization") or []

        lead = ""
        if total_issue is not None:
            lead = f"The issue size is approximately Rs {total_issue} crore"
        if fresh_issue is not None and ofs_cr is not None:
            lead = (lead + f", with a fresh issue of Rs {fresh_issue} crore and an offer for sale of Rs {ofs_cr} crore").strip(", ")
        elif fresh_issue is not None:
            lead = (lead + f", with a fresh issue component of Rs {fresh_issue} crore").strip(", ")
        elif ofs_cr is not None:
            lead = (lead + f", with an offer for sale component of Rs {ofs_cr} crore").strip(", ")

        summary_parts: list[str] = [lead] if lead else []

        if utilization:
            labels = [item.get("label") for item in utilization if item.get("label")]
            if labels:
                summary_parts.append(f"The filing says the fresh proceeds are mainly intended for {', '.join(labels[:3])}")

        sentence = ". ".join(part.rstrip(".") for part in summary_parts if part)
        return (sentence + ".") if sentence else "The filing does not provide a clean proceeds-allocation summary in the current extraction."

    def _build_financial_summary(self, financials: dict[str, Any], kpis: dict[str, Any]) -> str:
        trends = financials.get("trends") or {}
        flags = financials.get("flags") or []
        summary_parts: list[str] = []

        rev_cagr = trends.get("revenue_cagr_pct")
        pat_cagr = trends.get("pat_cagr_pct")
        if rev_cagr is not None or pat_cagr is not None:
            growth_bits: list[str] = []
            if rev_cagr is not None:
                growth_bits.append(f"revenue CAGR of {rev_cagr}%")
            if pat_cagr is not None:
                growth_bits.append(f"PAT CAGR of {pat_cagr}%")
            summary_parts.append("The restated financials indicate " + " and ".join(growth_bits))

        latest_margin = None
        margin_series = trends.get("ebitda_margin_pct") or []
        if isinstance(margin_series, list):
            numeric_margins = [value for value in margin_series if isinstance(value, (int, float))]
            if numeric_margins:
                latest_margin = numeric_margins[-1]
        if latest_margin is not None:
            summary_parts.append(f"The latest disclosed EBITDA margin is {latest_margin}%")
        elif kpis.get("ebitda_margin_pct") is not None:
            summary_parts.append(f"The filing reports EBITDA margin of {kpis['ebitda_margin_pct']}%")

        if flags:
            readable_flags = {
                "revenue_decline": "recent revenue decline",
                "pat_decline": "recent profit decline",
                "margin_compression": "margin compression",
                "rising_debt": "rising debt levels",
            }
            summary_parts.append(
                "Key watch-points include " + ", ".join(readable_flags.get(flag, flag.replace("_", " ")) for flag in flags[:3])
            )

        sentence = ". ".join(part.rstrip(".") for part in summary_parts if part)
        return (sentence + ".") if sentence else "Restated financial tables were not extracted cleanly from the current filing."

    def _build_valuation_summary(self, peer_valuation: dict[str, Any], kpis: dict[str, Any], filing: dict[str, Any]) -> str:
        ipo_pe = peer_valuation.get("ipo_pe")
        peer_avg_pe = peer_valuation.get("peer_avg_pe")
        premium_pct = peer_valuation.get("premium_pct")

        if ipo_pe is None:
            eps = kpis.get("eps")
            price_band_high = filing.get("price_band_high")
            if isinstance(eps, (int, float)) and eps not in (0, None) and isinstance(price_band_high, (int, float)):
                ipo_pe = round(float(price_band_high) / float(eps), 1)

        summary_parts: list[str] = []
        if ipo_pe is not None:
            summary_parts.append(f"At the upper end of the price band, the implied P/E works out to about {ipo_pe}x")
        if peer_avg_pe is not None:
            summary_parts.append(f"against an average peer multiple of {peer_avg_pe}x")
        if premium_pct is not None:
            direction = "premium" if premium_pct >= 0 else "discount"
            summary_parts.append(f"which places the issue at a {abs(premium_pct)}% {direction} to peers")
        if peer_valuation.get("historical_note"):
            summary_parts.append(str(peer_valuation["historical_note"]))

        sentence = ". ".join(part.rstrip(".") for part in summary_parts if part)
        return (sentence + ".") if sentence else "Comparable-company valuation data is limited in the current extraction."

    def _build_risk_summary(self, risks: dict[str, Any]) -> str:
        total_count = risks.get("total_count") or 0
        dominant_category = risks.get("dominant_category")
        if total_count <= 0:
            return "The filing's detailed risk-factor section has not yet been parsed into structured issue-specific risks."
        lead = f"The filing lists {total_count} structured risk factors"
        if dominant_category:
            lead += f", with the heaviest concentration in {str(dominant_category).replace('_', ' ')} risks"
        parts = [lead]
        if risks.get("regulatory_or_management_alert"):
            parts.append("Regulatory and management-linked disclosures form a meaningful share of the risk set")
        return ". ".join(part.rstrip(".") for part in parts if part) + "."

    def _build_governance_summary(self, promoters: dict[str, Any], management: list[dict[str, Any]], fraud_signals: list[dict[str, Any]]) -> str:
        promoter_count = len(promoters.get("promoters") or [])
        litigation_count = promoters.get("litigation_count") or 0
        management_count = len(management or [])
        summary_parts: list[str] = []

        if promoter_count:
            summary_parts.append(f"The filing identifies {promoter_count} promoter or promoter-group names")
        if management_count:
            summary_parts.append(f"and {management_count} key management personnel or directors")
        if litigation_count:
            summary_parts.append(f"The extracted litigation section references {litigation_count} potentially material legal matters")
        if fraud_signals:
            summary_parts.append(f"The governance screen triggered {len(fraud_signals)} disclosure-based alert signals")

        sentence = ". ".join(part.rstrip(".") for part in summary_parts if part)
        return (sentence + ".") if sentence else "Promoter, management, and litigation disclosures are limited in the current structured extraction."

    async def get_post_listing(self, slug: str) -> dict[str, Any] | None:
        """Get post-listing tracking data."""
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        tracking = await self.store.get_post_listing(slug)
        if not tracking:
            return None
        return {"filing": filing, "tracking": tracking}

    async def fetch_and_analyze(self, slug: str, *, pdf_path: str | None = None) -> dict[str, Any]:
        """Fetch and analyze document using the IPO PyMuPDF extraction pipeline."""
        filing = await self.store.get_filing(slug)
        if not filing and not pdf_path:
            raise ValueError(f"Unknown IPO slug: {slug}")
        
        # Get PDF
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
            raise ValueError(f"No PDF available for {slug}")
        
        pdf_bytes = Path(path).read_bytes()

        try:
            from finagent.ingestion.ipo_pdf_extractor import extract_ipo_pdf_markdown

            extraction = await extract_ipo_pdf_markdown(pdf_bytes, Path(path).name)
            markdown = extraction.markdown
            self._extraction_stats["pymupdf_success"] += 1
        except Exception:
            self._extraction_stats["extraction_failures"] += 1
            raise

        if not markdown.strip():
            self._extraction_stats["extraction_failures"] += 1
            raise ValueError(f"PyMuPDF extraction returned empty markdown for {slug}")
        
        # Parse DRHP sections using PARALLEL extractor for speed
        import time
        t_parse_start = time.perf_counter()
        parsed = await parse_drhp_markdown_parallel(markdown)
        t_parse = time.perf_counter() - t_parse_start
        logger.info("[PERF] DRHP parsing took %.2fs (parallel)", t_parse)

        parsed = self._hydrate_analysis_from_filing(parsed, filing or {})
        parsed["_parser_version"] = IPO_ANALYSIS_VERSION
        parsed["_extractor_used"] = extraction.extractor_used
        parsed["_extraction_diagnostics"] = extraction.diagnostics

        # Compute scores
        kpis_data = parsed.get("kpis") or {}
        ipo_pe = kpis_data.get("pe_ratio")
        eps = kpis_data.get("eps")
        price_band_high = (filing or {}).get("price_band_high")
        
        # Compute PE from price/EPS (more reliable)
        computed_pe = None
        if isinstance(eps, (int, float)) and eps not in (0, None) and isinstance(price_band_high, (int, float)):
            computed_pe = round(float(price_band_high) / float(eps), 1)
        
        # Filter peers: first row is often the issuer itself
        company_name_lower = (filing or {}).get("company_name", "").lower()
        raw_peers = parsed.get("peers") or []
        
        # Check if first peer in raw_peers is the issuer — use its PE as ipo_pe (more accurate)
        if raw_peers:
            first_company = raw_peers[0].get("company", "").lower()
            name_words = [w for w in company_name_lower.split() if len(w) > 3]
            if name_words and any(word in first_company for word in name_words[:2]):
                issuer_pe = raw_peers[0].get("pe")
                if issuer_pe and 1 < issuer_pe < 1000:
                    ipo_pe = issuer_pe  # Use peer-table PE (more accurate than KPI extractor)
        
        # If ipo_pe looks like the issue price (whole number matching price band), compute from EPS
        if ipo_pe and price_band_high and abs(ipo_pe - float(price_band_high)) < 5:
            ipo_pe = computed_pe
        if ipo_pe is None:
            ipo_pe = computed_pe
        
        # Remove issuer from peers list
        true_peers = [
            p for p in raw_peers
            if not (
                company_name_lower and
                any(word in p.get("company", "").lower() for word in company_name_lower.split()[:2] if len(word) > 3)
            )
        ]
        
        peer_valuation = compute_peer_valuation(true_peers, ipo_pe=ipo_pe)
        parsed["peer_valuation"] = peer_valuation
        parsed["valuation_summary"] = self._build_valuation_summary(peer_valuation, parsed.get("kpis") or {}, filing or {})
        scores = compute_ipo_score(parsed, peer_valuation=peer_valuation)
        
        # Save
        await self.store.save_analysis(slug, parsed)
        await self.store.save_scores(slug, scores)
        
        logger.info("Analyzed %s: composite_score=%s", slug, scores.get("composite_score"))
        
        return {"slug": slug, "analysis": parsed, "scores": scores}

    async def search_drhp(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Search IPO filings by query."""
        return await self.store.search(query, limit=limit)

    async def portfolio_ipo_links(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Get IPO tracking links for portfolio holdings."""
        await self.ensure_seed_data()
        return await self.store.portfolio_links(symbols)

    async def discover(self) -> list[dict[str, Any]]:
        """Discover new SEBI filings."""
        records = await discover_new_filings()
        return [record.__dict__ for record in records]

    def _to_card(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert filing to dashboard card format."""
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
            "bse_scrip_code": row.get("bse_scrip_code"),
            "is_sme": row.get("is_sme"),
            "listing_date": row.get("listing_date"),
            "allotment_date": row.get("allotment_date"),
        }

    def _build_lifecycle(self, filing: dict[str, Any]) -> dict[str, Any]:
        """Build IPO lifecycle stages with countdowns."""
        doc_type = str(filing.get("doc_type") or "drhp").lower()
        status = str(filing.get("status") or "upcoming").lower()
        has_rhp = doc_type in {"rhp", "prospectus"} or bool(filing.get("rhp_filing_date"))
        has_prospectus = doc_type == "prospectus" or bool(filing.get("prospectus_filing_date"))
        is_open = status == "live" or bool(filing.get("subscription_open"))
        is_listed = status == "listed" or bool(filing.get("listing_date"))
        
        now = datetime.now(timezone.utc).date()
        
        def stage_state(done: bool, active: bool = False) -> str:
            if active:
                return "current"
            return "done" if done else "pending"
        
        def _countdown(date_str: str | None) -> dict[str, Any] | None:
            if not date_str:
                return None
            try:
                target = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                days = (target - now).days
                if days < 0:
                    return None
                return {"days": days, "target_date": date_str}
            except (ValueError, TypeError):
                return None
        
        stages = [
            {
                "key": "drhp",
                "label": "DRHP Filed",
                "description": "Draft Red Herring Prospectus filed with SEBI",
                "state": stage_state(True, doc_type == "drhp" and not is_open and not is_listed),
                "date": filing.get("filing_date"),
                "pdf_url": filing.get("pdf_url") if doc_type == "drhp" else None,
            },
            {
                "key": "rhp",
                "label": "RHP Approved",
                "description": "Red Herring Prospectus approved by SEBI",
                "state": stage_state(has_rhp, doc_type == "rhp" and not is_open and not is_listed),
                "date": filing.get("rhp_filing_date") or (filing.get("filing_date") if has_rhp else None),
                "pdf_url": filing.get("pdf_url") if doc_type == "rhp" else None,
            },
            {
                "key": "ipo_open",
                "label": "Bidding Open",
                "description": "IPO subscription window",
                "state": stage_state(is_open or is_listed, status == "live"),
                "date": filing.get("subscription_open"),
                "end_date": filing.get("subscription_close"),
                "countdown": _countdown(filing.get("subscription_close")) if status == "live" else _countdown(filing.get("subscription_open")),
            },
            {
                "key": "allotment",
                "label": "Allotment",
                "description": "Share allotment finalized",
                "state": stage_state(bool(filing.get("allotment_date")) or is_listed, False),
                "date": filing.get("allotment_date"),
                "countdown": _countdown(filing.get("allotment_date")),
            },
            {
                "key": "listed",
                "label": "Listed",
                "description": "Trading commenced on exchange",
                "state": stage_state(is_listed, status == "listed"),
                "date": filing.get("listing_date"),
                "countdown": _countdown(filing.get("listing_date")),
            },
        ]
        
        if has_prospectus:
            stages[1]["description"] = "RHP / Final Prospectus available"
        
        return {
            "current_doc_type": doc_type,
            "current_status": status,
            "source": filing.get("source") or "sebi",
            "latest_document_url": filing.get("pdf_url"),
            "latest_document_date": filing.get("filing_date"),
            "stages": stages,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def get_extraction_stats(self) -> dict[str, int]:
        """Get document extraction statistics."""
        return dict(self._extraction_stats)


_service: IpoService | None = None


def get_ipo_service() -> IpoService:
    global _service
    if _service is None:
        _service = IpoService()
    return _service
