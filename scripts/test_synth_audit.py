"""Focused audit: exercise the CHANGED stages (article synth + archetype + editorial
+ gate + word count) directly, skipping the slow 8-pass research crawl."""
import asyncio, os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / "finagent" / ".env")

from finagent.content.flash_engine import (
    FlashGenerationRequest, _direct_json_article_call, _build_evidence_pack,
    _build_evidence_claims, _evaluate_publish_gate, _article_body_word_count,
    _article_word_count, _article_plain_text, _effective_content_type,
    _expand_article_sections, _ensure_narrative_lede,
)
from finagent.content.editorial import run_editorial_revision_loop, sanitize_article_package
from finagent.content.archetype import classify_archetype

MEMO = """Infosys Q2 FY26 results (filed BSE/NSE 2025-10-16):
Revenue Rs 42,310 crore, +8.6% YoY, +2.1% QoQ. PAT Rs 6,920 crore, +13.2% YoY.
EBIT margin 21.3%, +40 bps QoQ. FY26 cc revenue growth guidance raised to 3.0-4.0% (from 1.0-3.0%).
Large-deal TCV USD 3.8 billion, 56% net-new. LTM attrition 13.4% (down from 14.1%).
Headcount 3,29,900, +8,200 QoQ. FCF Rs 7,540 crore, FCF/PAT 109%. Interim dividend Rs 21/share.
BFSI and manufacturing led; communications soft. Peer TCS grew 5.9% YoY; HCLTech raised lower-end guidance.
Stock reaction: +3% intraday. Street had pencilled 7-8% YoY revenue and 21.0% margin."""

async def main():
    req = FlashGenerationRequest(mode="deep", content_type="earnings",
        target="Infosys Q2 FY26 results", source_markdown=MEMO, route_base="insights",
        include_image=False, overwrite=True)
    slug = "infosys-q2-fy26-audit"
    ct = _effective_content_type(req)

    print("[1] article LLM synth...", flush=True)
    art = await _direct_json_article_call(MEMO, {}, req, slug, ct)
    if art is None:
        print("ARTICLE GEN FAILED"); return
    art = sanitize_article_package(art)

    arch = classify_archetype(req.target, req.content_type, _article_plain_text(art) + " " + MEMO)
    print(f"[2] archetype = {arch}", flush=True)

    ev = _build_evidence_pack(req, {}, {})
    pre_claims = _build_evidence_claims(art, ev)
    print(f"[3] editorial loop (archetype={arch})...", flush=True)
    art, review = await run_editorial_revision_loop(art, target=req.target, max_rounds=2,
        is_official_source=True, quality_score=70, evidence_claim_count=len(pre_claims),
        source_material=MEMO, archetype=arch)
    art = sanitize_article_package(art)
    pre = _article_body_word_count(art)
    art = await _expand_article_sections(art, MEMO, req)
    art = sanitize_article_package(art)
    art = _ensure_narrative_lede(art)
    print(f"[3b] section-writer body words {pre} -> {_article_body_word_count(art)}; lede_set={bool((art.narrative_lede or '').strip())}", flush=True)
    claims = _build_evidence_claims(art, ev)
    gate = _evaluate_publish_gate(req=req, article=art, editorial_review=review,
        quality_score=int(review.total_score), evidence_pack=ev, evidence_claims=claims)

    out = {
        "title": art.title, "description": art.description,
        "archetype": arch,
        "body_words": _article_body_word_count(art), "total_words": _article_word_count(art),
        "sections": [(s.heading, len(s.paragraphs), sum(len(p.split()) for p in s.paragraphs)) for s in art.sections],
        "metrics": [(m.label, m.value, m.source) for m in art.metrics],
        "n_faqs": len(art.faqs), "n_visuals": len(art.visuals), "n_tables": len(art.tables),
        "n_timeline": len(art.timeline), "n_evidence_notes": len(art.evidence_notes),
        "editorial_score": review.total_score, "livemint_score": review.livemint_score,
        "ready_to_publish": review.ready_to_publish,
        "critical_issues": [i.code for i in review.issues if i.severity == "critical"],
        "gate_status": gate["status"], "gate_score": gate["score"], "gate_reasons": gate["reasons"],
    }
    Path(ROOT / ".proxy" / "audit_article.json").write_text(json.dumps({
        "audit": out, "article": art.model_dump()}, indent=2, ensure_ascii=True), encoding="utf-8")
    print("=== AUDIT ===")
    print(json.dumps(out, indent=2, ensure_ascii=True))
    print("\n=== LEDE ==="); print(getattr(art, "narrative_lede", "") or "")
    print("\n=== SECTION 1 FULL ==="); print("\n\n".join(art.sections[1].paragraphs) if len(art.sections)>1 else "")

asyncio.run(main())
