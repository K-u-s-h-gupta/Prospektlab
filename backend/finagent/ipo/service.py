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
from finagent.tools.data.ipo_fetcher import (
    IpoFilingRecord,
    discover_new_filings,
    download_drhp,
    load_cached_pdf,
    run_daily_watcher,
    slugify_company,
)

logger = logging.getLogger("finagent.ipo.service")

# Demo seed data so UI works before live pipeline populates
_DEMO_IPOS: list[dict[str, Any]] = [
    {
        "slug": "swiggy",
        "company_name": "Swiggy Limited",
        "sector": "Consumer / Quick Commerce",
        "exchange": "NSE",
        "status": "listed",
        "doc_type": "drhp",
        "issue_size_cr": 11300,
        "fresh_issue_cr": 7000,
        "ofs_cr": 4300,
        "price_band_low": 371,
        "price_band_high": 390,
        "gmp": 18,
        "subscription_status": "Closed — fully subscribed",
        "listing_date": (date.today() - timedelta(days=45)).isoformat(),
        "composite_score": 68.4,
        "scores": {
            "business_quality": 72,
            "valuation_fairness": 58,
            "management_credibility": 70,
            "financial_health": 65,
            "risk_profile": 71,
        },
    },
    {
        "slug": "boat-parent",
        "company_name": "Imagine Marketing Limited (boAt)",
        "sector": "Consumer Electronics",
        "exchange": "NSE",
        "status": "live",
        "doc_type": "rhp",
        "issue_size_cr": 1500,
        "fresh_issue_cr": 900,
        "ofs_cr": 600,
        "price_band_low": 410,
        "price_band_high": 432,
        "gmp": 42,
        "subscription_status": "Day 2 — 1.8x subscribed",
        "listing_date": None,
        "composite_score": 61.2,
        "scores": {
            "business_quality": 66,
            "valuation_fairness": 52,
            "management_credibility": 64,
            "financial_health": 62,
            "risk_profile": 63,
        },
    },
    {
        "slug": "techwave-sme",
        "company_name": "TechWave Components Limited",
        "sector": "Electronics Manufacturing (SME)",
        "exchange": "BSE SME",
        "status": "upcoming",
        "doc_type": "drhp",
        "issue_size_cr": 42,
        "fresh_issue_cr": 42,
        "ofs_cr": 0,
        "price_band_low": 95,
        "price_band_high": 100,
        "gmp": None,
        "subscription_status": "DRHP filed — subscription not open",
        "listing_date": None,
        "composite_score": 54.8,
        "scores": {
            "business_quality": 58,
            "valuation_fairness": 55,
            "management_credibility": 48,
            "financial_health": 52,
            "risk_profile": 56,
        },
    },
]


class IpoService:
    def __init__(self, store: IpoStore | None = None):
        self.store = store or get_ipo_store()

    async def ensure_seed_data(self) -> None:
        existing = await self.store.list_filings(limit=1)
        if existing:
            return
        for item in _DEMO_IPOS:
            await self.store.upsert_filing(item)

    async def run_watcher(self, *, download: bool = True) -> dict[str, Any]:
        result = await run_daily_watcher(download=download)
        for raw in result.get("records", []):
            record = IpoFilingRecord(**{k: raw[k] for k in raw if k in IpoFilingRecord.__dataclass_fields__})
            await self.store.upsert_filing(
                {
                    "slug": record.slug,
                    "company_name": record.company_name,
                    "doc_type": record.doc_type,
                    "filing_date": record.filing_date,
                    "pdf_url": record.pdf_url,
                    "exchange": record.exchange,
                    "source": record.source,
                    "status": "upcoming",
                }
            )
        return result

    async def pipeline_dashboard(self) -> dict[str, Any]:
        await self.ensure_seed_data()
        filings = await self.store.list_filings(limit=200)
        buckets = {"upcoming": [], "live": [], "listed": []}
        for row in filings:
            status = (row.get("status") or "upcoming").lower()
            if status not in buckets:
                status = "upcoming"
            card = self._to_card(row)
            buckets[status].append(card)
        return {
            "as_of": datetime.utcnow().isoformat() + "Z",
            "buckets": buckets,
            "gmp_disclaimer": (
                "Grey Market Premium (GMP) reflects informal off-exchange sentiment and is not a price guarantee. "
                "Use alongside the ProspektLab IPO Score for fundamental context."
            ),
        }

    async def get_analysis(self, slug: str) -> dict[str, Any] | None:
        await self.ensure_seed_data()
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        analysis = await self.store.get_analysis(slug)
        scores = await self.store.get_scores(slug)
        if not analysis:
            analysis = self._demo_analysis(filing)
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
            "analysis": analysis,
            "scores": scores,
            "peer_valuation": analysis.get("peer_valuation") or {},
        }

    async def get_post_listing(self, slug: str) -> dict[str, Any] | None:
        filing = await self.store.get_filing(slug)
        if not filing:
            return None
        tracking = await self.store.get_post_listing(slug)
        if not tracking:
            issue_price = filing.get("price_band_high") or filing.get("price_band_low")
            tracking = {
                "issue_price": issue_price,
                "listing_price": round(float(issue_price or 0) * 1.12, 2) if issue_price else None,
                "listing_gain_pct": 12.0,
                "current_return_pct": 8.5,
                "drhp_promises": [
                    {"objective": "Expand dark-store network", "status": "on_track"},
                    {"objective": "Reduce adjusted EBITDA losses", "status": "mixed"},
                    {"objective": "Invest in Instamart infrastructure", "status": "on_track"},
                ],
                "on_track": True,
            }
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
            "subscription_status": row.get("subscription_status"),
            "listing_date": row.get("listing_date"),
        }

    def _demo_analysis(self, filing: dict[str, Any]) -> dict[str, Any]:
        slug = filing.get("slug", "")
        fresh = filing.get("fresh_issue_cr") or 0
        ofs = filing.get("ofs_cr") or 0
        total = fresh + ofs or 1
        return {
            "business_synthesis": (
                f"{filing.get('company_name')} operates in {filing.get('sector', 'its sector')} with a "
                "document-backed revenue model described in the DRHP Business Overview section. "
                "Primary growth is tied to market expansion and operating leverage rather than one-off gains."
            ),
            "financials": {
                "years": ["FY22", "FY23", "FY24"],
                "metrics": {
                    "revenue": [820, 1040, 1280],
                    "pat": [45, 62, 74],
                    "ebitda": [110, 145, 176],
                },
                "trends": {"revenue_cagr_pct": 24.8, "pat_cagr_pct": 28.2, "ebitda_margin_pct": [13.4, 13.9, 13.8]},
                "flags": [],
            },
            "objects_of_issue": {
                "fresh_issue_cr": fresh,
                "ofs_cr": ofs,
                "ofs_pct": round(100.0 * ofs / total, 1),
                "utilization": [
                    {"category": "capex", "label": "Capacity expansion", "amount_cr": round(fresh * 0.35, 1)},
                    {"category": "debt_repayment", "label": "Debt repayment", "amount_cr": round(fresh * 0.25, 1)},
                    {"category": "general_corporate", "label": "General corporate purposes", "amount_cr": round(fresh * 0.20, 1)},
                ],
                "flags": ["high_ofs_exit_signal"] if ofs / total >= 0.5 else [],
            },
            "risk_factors": {
                "total_count": 87,
                "dominant_category": "business",
                "by_category": {
                    "business": {"count": 32, "severity_score": 58},
                    "regulatory": {"count": 14, "severity_score": 31},
                    "financial": {"count": 18, "severity_score": 36},
                    "management": {"count": 11, "severity_score": 24},
                    "market": {"count": 12, "severity_score": 22},
                },
                "top_risks": [
                    {"number": 1, "text": "Intense competition may affect pricing power and market share.", "severity": "high", "category": "business"},
                    {"number": 2, "text": "Regulatory changes in the sector could increase compliance costs.", "severity": "medium", "category": "regulatory"},
                ],
            },
            "promoters": {
                "promoters": [{"name": "Mr. Promoter A"}, {"name": "Ms. Promoter B"}],
                "litigation_count": 1,
                "litigation_snippets": ["No material SEBI enforcement action disclosed in DRHP litigation section."],
            },
            "peer_valuation": compute_peer_valuation(
                [
                    {"company": "Peer Alpha Ltd", "pe": 34.2, "ev_ebitda": 22.1},
                    {"company": "Peer Beta Ltd", "pe": 29.8, "ev_ebitda": 19.4},
                ],
                ipo_pe=41.5 if slug == "swiggy" else 38.0,
            ),
            "fraud_signals": [] if slug != "techwave-sme" else [
                {"code": "high_related_party", "label": "Related-party transactions exceed 30% threshold", "governance_alert": "true"},
                {"code": "high_gcp", "label": "More than 60% of fresh issue allocated to general corporate purposes", "governance_alert": "true"},
            ],
        }


_service: IpoService | None = None


def get_ipo_service() -> IpoService:
    global _service
    if _service is None:
        _service = IpoService()
    return _service
