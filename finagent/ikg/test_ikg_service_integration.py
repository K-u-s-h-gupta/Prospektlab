from __future__ import annotations

import asyncio

from finagent.analysis.conflicts import MetricObservation, detect_conflicts
from finagent.ikg.entity_resolver import IKGEntityResolver
from finagent.ikg.graph_client import IKGClient, InMemoryGraphBackend
from finagent.ikg.service import IKGCompanyBundle, IKGService, _bundle_cache, metric_observations_from_bundle


class _ResolverStub:
    def resolve_by_cin(self, cin: str):
        return None

    def resolve_by_ticker(self, ticker: str):
        return None

    def resolve_by_isin(self, isin: str):
        return None

    def resolve(self, identifier: str):
        return None


class _CanonicalFallbackResolver(IKGEntityResolver):
    def __init__(self):
        super().__init__(database_url="postgresql://stub")

    def _fetch_rows(self, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        if "from ikg_company_master" in sql:
            return []
        if "properties->>'nse_symbol'" in sql or "upper(coalesce(ea.alias" in sql:
            return [
                {
                    "entity_id": "company:L123",
                    "display_name": "Acme Solar Holdings Limited",
                    "primary_identifier": "L123",
                    "properties": {
                        "cin": "L123",
                        "nse_symbol": "ACME",
                        "bse_scrip_code": "500001",
                        "isin": "INE000A01010",
                        "sector": "Industrials",
                    },
                    "confidence": 0.93,
                }
            ]
        return []


class _FallbackService(IKGService):
    def __init__(self, **kwargs):
        super().__init__(database_url="postgresql://stub", **kwargs)

    def _fetch_rows(self, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        if "from ikg_company_master" in sql:
            return []
        if "from ikg_canonical_entities" in sql:
            return [
                {
                    "entity_id": "company:L123",
                    "display_name": "Acme Solar Holdings Limited",
                    "primary_identifier": "L123",
                    "properties": {
                        "cin": "L123",
                        "nse_symbol": "ACME",
                        "bse_scrip_code": "500001",
                        "isin": "INE000A01010",
                        "sector": "Industrials",
                        "industry": "Solar",
                    },
                }
            ]
        if "from ikg_ownership_summary" in sql:
            return [
                {
                    "company_vertex_id": "company:L123",
                    "owner_vertex_id": "promoter:group",
                    "owner_name": "Acme Promoter Group",
                    "quarter": "129",
                    "holding_pct": 40.0,
                    "pledge_pct": 25.0,
                    "source_table": "shp_raw",
                    "source_uid": "500001:129",
                    "source_url": "https://www.bseindia.com/shareholding",
                    "updated_at": "2026-06-05T00:00:00Z",
                }
            ]
        return []


class _SqlCaptureService(IKGService):
    def __init__(self, **kwargs):
        super().__init__(database_url="postgresql://stub", **kwargs)
        self.last_sql = ""
        self.last_params: tuple[object, ...] = ()

    def _fetch_rows(self, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        self.last_sql = sql
        self.last_params = params
        return []


def test_build_company_bundle_from_memory_graph():
    backend = InMemoryGraphBackend()
    backend.upsert_vertex(
        "company:L123",
        "Company",
        {
            "name": "Acme Limited",
            "nse_symbol": "ACME",
            "source_url": "https://www.nseindia.com/acme",
            "total_revenue": 1200.0,
            "net_income": 150.0,
        },
    )
    backend.upsert_vertex("person:001", "Person", {"name": "Jane Director", "source_url": "https://www.bseindia.com/dir"})
    backend.upsert_vertex("promoter:group", "PromoterGroup", {"name": "Acme Promoters"})
    backend.upsert_edge(
        "person:001",
        "company:L123",
        "DIRECTOR_OF",
        {"source_url": "https://www.bseindia.com/dir"},
    )
    backend.upsert_edge(
        "promoter:group",
        "company:L123",
        "OWNS_STAKE_IN",
        {
            "percentage": 55.0,
            "pledge_pct": 12.0,
            "source_url": "https://www.nseindia.com/shareholding",
        },
    )
    client = IKGClient(backend=backend)
    service = IKGService(graph_client=client, entity_resolver=_ResolverStub(), database_url="")

    bundle = asyncio.run(
        service.build_company_bundle(
            cin="L123",
            ticker="ACME",
            name="Acme Limited",
            depth="standard",
        )
    )

    assert bundle.status in {"ok", "partial"}
    assert bundle.entity["cin"] == "L123"
    assert bundle.coverage["governance"] != "missing"
    assert bundle.coverage["ownership"] != "missing"
    assert any("Promoter pledge" in fact["headline"] for fact in bundle.facts)
    assert "https://www.nseindia.com/shareholding" in bundle.source_refs


def test_metric_observations_from_bundle_maps_financial_fields():
    bundle = IKGCompanyBundle(
        status="ok",
        entity={"cin": "L123", "name": "Acme Limited"},
        financials={"company_financials": {"total_revenue": 1200.0, "net_income": 150.0, "eps": 12.5}},
        source_refs=["https://www.nseindia.com/acme"],
    )

    observations = metric_observations_from_bundle(bundle)

    metrics = {item.metric for item in observations}
    assert {"revenue", "net_income", "eps"} <= metrics


def test_detect_conflicts_accepts_external_observations():
    observations = [
        MetricObservation(
            metric="revenue",
            value=1200.0,
            raw="1200",
            context="IKG revenue",
            url="ikg://bundle",
            domain="ikg",
            tier=1,
        ),
        MetricObservation(
            metric="revenue",
            value=800.0,
            raw="800",
            context="secondary source revenue",
            url="https://example.com/source",
            domain="example.com",
            tier=4,
        ),
    ]

    reports = detect_conflicts([], external_observations=observations)

    assert len(reports) == 1
    assert reports[0].metric == "revenue"
    assert reports[0].spread_pct > 30


def test_entity_resolver_falls_back_to_canonical_entities_for_ticker():
    resolver = _CanonicalFallbackResolver()

    entity = resolver.resolve_by_ticker("ACME")

    assert entity is not None
    assert entity.cin == "L123"
    assert entity.name == "Acme Solar Holdings Limited"
    assert entity.nse_symbol == "ACME"
    assert entity.source == "ikg_aliases"


def test_build_company_bundle_uses_canonical_and_ownership_fallbacks():
    backend = InMemoryGraphBackend()
    client = IKGClient(backend=backend)
    service = _FallbackService(graph_client=client, entity_resolver=_ResolverStub())

    bundle = asyncio.run(
        service.build_company_bundle(
            cin="L123",
            ticker="ACME",
            name="Acme Solar Holdings Limited",
            depth="standard",
        )
    )

    assert bundle.company is not None
    assert bundle.company["company_name"] == "Acme Solar Holdings Limited"
    assert bundle.coverage["identity"] == "complete"
    assert bundle.coverage["ownership"] != "missing"
    assert bundle.ownership["pledge_summary"]["total_promoter_holding_pct"] == 40.0
    assert bundle.ownership["pledge_summary"]["total_pledge_pct"] == 10.0


def test_build_company_bundle_prefers_dated_ownership_summary_over_graph_edges():
    _bundle_cache.clear()
    backend = InMemoryGraphBackend()
    backend.upsert_vertex("company:L123", "Company", {"cin": "L123", "nse_symbol": "ACME"})
    backend.upsert_vertex("promoter:stale", "PromoterGroup", {"name": "Stale Promoter"})
    backend.upsert_edge(
        "promoter:stale",
        "company:L123",
        "OWNS_STAKE_IN",
        {"percentage": 99.0, "pledge_pct": 99.0, "quarter": "old"},
    )
    service = _FallbackService(graph_client=IKGClient(backend=backend), entity_resolver=_ResolverStub())

    bundle = asyncio.run(
        service.build_company_bundle(
            cin="L123",
            ticker="ACME",
            name="Acme Solar Holdings Limited",
            depth="standard",
        )
    )

    assert bundle.ownership["pledge_summary"]["total_promoter_holding_pct"] == 40.0
    assert bundle.ownership["promoters"][0]["owner_name"] == "Acme Promoter Group"
    assert bundle.ownership["graph_pledge_summary"]["total_promoter_holding_pct"] == 99.0


def test_corporate_filings_query_includes_raw_and_xbrl_sources():
    service = _SqlCaptureService(graph_client=IKGClient(backend=InMemoryGraphBackend()), entity_resolver=_ResolverStub())

    asyncio.run(service.get_corporate_filings("L123", limit=7))

    assert "from corporate_filings_raw" in service.last_sql
    assert "from xbrl_filings_raw" in service.last_sql
    assert service.last_params == ("L123", "L123", 7)


def test_document_section_search_checks_cin_alias_metadata_keys():
    service = _SqlCaptureService(graph_client=IKGClient(backend=InMemoryGraphBackend()), entity_resolver=_ResolverStub())

    asyncio.run(service.search_document_sections("L123", query="auditor", limit=3))

    assert "metadata->>'cin'" in service.last_sql
    assert "metadata->>'company_cin'" in service.last_sql
    assert "metadata->>'company_identifier'" in service.last_sql
    assert service.last_params[:3] == ("L123", "L123", "L123")
