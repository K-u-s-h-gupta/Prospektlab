"""Tests for the Livemint source blocker."""

from __future__ import annotations

from finagent.content.livemint_blocker import (
    evidence_pack_livemint_count,
    is_livemint_url,
    sanitise_evidence_pack,
    strip_livemint_sources,
)


def test_is_livemint_url_matches_host_and_subdomain() -> None:
    assert is_livemint_url("https://www.livemint.com/article")
    assert is_livemint_url("https://markets.livemint.com/x")
    assert not is_livemint_url("https://reuters.com/x")
    assert not is_livemint_url("https://livemintish.com/x")
    assert not is_livemint_url("")
    assert not is_livemint_url(None)


def test_is_livemint_url_falls_back_to_bare_match() -> None:
    # Malformed URL where urlparse fails to detect the host.
    assert is_livemint_url("livemint.com/article-without-scheme")


def test_strip_livemint_sources_drops_and_counts() -> None:
    items = [
        {"title": "BSE", "url": "https://bseindia.com/x"},
        {"title": "Mint", "url": "https://www.livemint.com/x"},
        {"title": "Reuters", "url": "https://reuters.com/x"},
    ]
    cleaned, dropped = strip_livemint_sources(items)
    assert dropped == 1
    assert {item["title"] for item in cleaned} == {"BSE", "Reuters"}


def test_evidence_pack_livemint_count_scans_all_buckets() -> None:
    pack = {
        "official_document_evidence": [{"url": "https://nseindia.com/x"}],
        "trusted_supporting_sources": [
            {"url": "https://reuters.com/x"},
            {"url": "https://www.livemint.com/x"},
        ],
        "sources_used": [{"url": "https://www.livemint.com/y"}],
    }
    assert evidence_pack_livemint_count(pack) == 2


def test_sanitise_evidence_pack_returns_clean_copy() -> None:
    pack = {
        "official_document_evidence": [{"url": "https://nseindia.com/x"}],
        "trusted_supporting_sources": [
            {"url": "https://www.livemint.com/x"},
            {"url": "https://reuters.com/x"},
        ],
    }
    cleaned, dropped = sanitise_evidence_pack(pack)
    assert dropped == 1
    assert len(cleaned["trusted_supporting_sources"]) == 1
    assert cleaned["trusted_supporting_sources"][0]["url"].startswith("https://reuters.com")
    # Original untouched.
    assert len(pack["trusted_supporting_sources"]) == 2
