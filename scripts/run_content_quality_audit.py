from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

from finagent.content.flash_engine import FlashGenerationRequest, generate_flash_article


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _count_digits(text: str) -> int:
    return len(re.findall(r"\d", text or ""))


def _extract_article(payload: dict[str, Any]) -> dict[str, Any]:
    article = payload.get("article")
    if isinstance(article, dict):
        return article
    return {}


def _audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    article = _extract_article(payload)
    publish_gate = payload.get("publish_gate") if isinstance(payload.get("publish_gate"), dict) else {}
    metrics = publish_gate.get("metrics") if isinstance(publish_gate.get("metrics"), dict) else {}

    sections = article.get("sections") if isinstance(article.get("sections"), list) else []
    section_word_counts: list[int] = []
    paragraph_count = 0
    total_words = 0
    total_numeric_tokens = 0

    for section in sections:
        if not isinstance(section, dict):
            continue
        section_words = 0
        for paragraph in (section.get("paragraphs") or []):
            if not isinstance(paragraph, str):
                continue
            paragraph_count += 1
            wc = _word_count(paragraph)
            section_words += wc
            total_words += wc
            total_numeric_tokens += _count_digits(paragraph)
        for bullet in (section.get("bullets") or []):
            if not isinstance(bullet, str):
                continue
            wc = _word_count(bullet)
            section_words += wc
            total_words += wc
            total_numeric_tokens += _count_digits(bullet)
        if section_words > 0:
            section_word_counts.append(section_words)

    sources_used = payload.get("sources_used") if isinstance(payload.get("sources_used"), list) else []
    official_sources = 0
    trusted_sources = 0
    for source in sources_used:
        if not isinstance(source, dict):
            continue
        evidence_type = str(source.get("evidence_type") or "").strip().lower()
        if evidence_type == "official_document":
            official_sources += 1
        if evidence_type == "trusted_supporting":
            trusted_sources += 1

    research_dimensions = metrics.get("research_dimensions") if isinstance(metrics.get("research_dimensions"), dict) else {}
    all_research_dimensions_present = bool(research_dimensions) and all(bool(v) for v in research_dimensions.values())

    score = int(publish_gate.get("score") or payload.get("confidence_score") or 0)
    gate_status = str(publish_gate.get("status") or payload.get("publish_gate_status") or "").strip().lower()
    evidence_score = int(metrics.get("evidence_score") or 0)
    gate_word_count = int(metrics.get("word_count") or 0)
    effective_word_count = gate_word_count if gate_word_count > 0 else total_words

    accuracy_proxy_pass = (
        official_sources >= 1
        and trusted_sources >= 2
        and evidence_score >= 85
        and int(metrics.get("evidence_claim_count") or 0) >= 6
    )
    depth_proxy_pass = (
        effective_word_count >= 1800
        and len(section_word_counts) >= 5
        and paragraph_count >= 10
        and int(metrics.get("table_count") or 0) >= 1
        and int(metrics.get("visual_count") or 0) >= 1
    )
    quality_pass = (
        gate_status == "publish"
        and score >= 85
        and all_research_dimensions_present
        and int(metrics.get("source_score") or 0) >= 80
        and int(metrics.get("editorial_score") or 0) >= 80
    )

    return {
        "publish_gate_status": gate_status or "unknown",
        "publish_gate_score": score,
        "publish_status": str(payload.get("publish_status") or "").strip().lower(),
        "quality_pass": quality_pass,
        "accuracy_proxy_pass": accuracy_proxy_pass,
        "depth_proxy_pass": depth_proxy_pass,
        "all_research_dimensions_present": all_research_dimensions_present,
        "gate_word_count": gate_word_count,
        "effective_word_count": effective_word_count,
        "computed_word_count": total_words,
        "computed_paragraph_count": paragraph_count,
        "computed_numeric_token_count": total_numeric_tokens,
        "source_count": len(sources_used),
        "official_source_count": official_sources,
        "trusted_supporting_source_count": trusted_sources,
        "metrics": {
            "editorial_score": int(metrics.get("editorial_score") or 0),
            "source_score": int(metrics.get("source_score") or 0),
            "depth_score": int(metrics.get("depth_score") or 0),
            "evidence_score": evidence_score,
            "section_count": int(metrics.get("section_count") or 0),
            "substantive_sections": int(metrics.get("substantive_sections") or 0),
            "table_count": int(metrics.get("table_count") or 0),
            "visual_count": int(metrics.get("visual_count") or 0),
            "timeline_count": int(metrics.get("timeline_count") or 0),
            "evidence_note_count": int(metrics.get("evidence_note_count") or 0),
            "evidence_claim_count": int(metrics.get("evidence_claim_count") or 0),
        },
        "research_dimensions": research_dimensions,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.json_path:
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        return {
            "result": {
                "slug": payload.get("slug"),
                "title": payload.get("title"),
                "route_base": payload.get("route_base"),
                "public_url": payload.get("public_url"),
                "html_path": payload.get("html_path"),
                "json_path": payload.get("json_path") or args.json_path,
            },
            "audit": _audit_payload(payload),
            "json_path": payload.get("json_path") or args.json_path,
            "html_path": payload.get("html_path"),
            "public_url": payload.get("public_url"),
        }

    source_meta: dict[str, Any] | None = None
    if args.source_url:
        source_meta = {
            "source_url": args.source_url,
            "attachment_url": args.source_url,
            "attachment_document_type": args.attachment_type,
            "attachment_extraction_status": "ok",
            "attachment_text_sufficient": True,
            "attachment_parser": "docling",
            "attachment_text": args.attachment_text,
            "attachment_structured_facts": {
                "event_date": args.event_date,
                "company": args.company_name,
                "filing_type": args.filing_type,
                "exchange": args.exchange,
            },
            "attachment_tables": [],
        }

    req = FlashGenerationRequest(
        mode=args.mode,
        content_type=args.content_type,
        target=args.target,
        objective=args.objective,
        source_url=args.source_url,
        source_evidence_meta=source_meta,
        route_base=args.route_base,
        force_publish=False,
        include_image=not args.no_image,
        overwrite=True,
    )

    job_id = f"audit-{uuid.uuid4().hex[:8]}"
    result = await generate_flash_article(req, job_id=job_id, requested_by=args.requested_by)
    payload = json.loads(Path(result.json_path).read_text(encoding="utf-8"))
    audit = _audit_payload(payload)

    return {
        "result": result.model_dump(),
        "audit": audit,
        "json_path": result.json_path,
        "html_path": result.html_path,
        "public_url": result.public_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one research article and run quality/depth audit.")
    parser.add_argument("--mode", default="flash", choices=["flash", "deep", "research"])
    parser.add_argument("--content-type", default="company", choices=["earnings", "sebi", "trend", "company", "manual"])
    parser.add_argument("--target", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument("--route-base", default="insights")
    parser.add_argument("--source-url")
    parser.add_argument("--attachment-type", default="pdf")
    parser.add_argument("--attachment-text", default="Official filing evidence extracted successfully.")
    parser.add_argument("--event-date", default="2026-06-05")
    parser.add_argument("--company-name", default="Unknown Company")
    parser.add_argument("--filing-type", default="Official Update")
    parser.add_argument("--exchange", default="NSE/BSE")
    parser.add_argument("--requested-by", default="local-audit@prospektlab.ai")
    parser.add_argument("--no-image", action="store_true")
    parser.add_argument("--json-path")
    args = parser.parse_args()
    if not args.json_path and (not args.target or not args.objective):
        parser.error("--target and --objective are required unless --json-path is provided")

    out = asyncio.run(_run(args))
    print(json.dumps(out, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
