"""Domain-specific Crawl4AI extraction configs for Indian market sites.

These overrides are merged into the base CrawlerRunConfig when the batch
is dominated by a single known domain, improving extraction quality for
structured pages (circulars, tables, filings).
"""

from __future__ import annotations

from crawl4ai import CrawlerRunConfig

SEBI_CONFIG = CrawlerRunConfig(
    excluded_tags=["nav", "footer", "header", "aside", "form", "script", "style"],
    css_selector="div.content, div.container, table.dataTable, div#main-content",
    word_count_threshold=5,
)

NSE_CONFIG = CrawlerRunConfig(
    excluded_tags=["nav", "footer", "header", "aside", "form"],
    css_selector="div#companyInfo, div.corporate-filing, table, div.content-area",
    word_count_threshold=5,
)

BSE_CONFIG = CrawlerRunConfig(
    excluded_tags=["nav", "footer", "header", "aside", "form"],
    css_selector="div.bse-table, div.content-area, table, div#main-content",
    word_count_threshold=5,
)

_DOMAIN_OVERRIDES: dict[str, CrawlerRunConfig] = {
    "sebi.gov.in": SEBI_CONFIG,
    "nseindia.com": NSE_CONFIG,
    "bseindia.com": BSE_CONFIG,
}


def apply_domain_override(base_cfg: CrawlerRunConfig, urls: list[str]) -> CrawlerRunConfig:
    """If all URLs share a known domain, merge its override into base config.

    Returns a new CrawlerRunConfig with merged settings.
    """
    if not urls:
        return base_cfg
    from urllib.parse import urlparse
    domains = {urlparse(u).hostname or "" for u in urls}
    if len(domains) != 1:
        return base_cfg
    domain = next(iter(domains)).lower().removeprefix("www.")
    override = _DOMAIN_OVERRIDES.get(domain)
    if not override:
        return base_cfg
    # Merge: override fields take precedence where set
    import dataclasses
    base_dict = dataclasses.asdict(base_cfg)
    override_dict = dataclasses.asdict(override)
    merged = {**base_dict, **{k: v for k, v in override_dict.items() if v}}
    return CrawlerRunConfig(**merged)
