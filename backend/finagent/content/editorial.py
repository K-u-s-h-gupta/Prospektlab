"""Editorial review and auto-revision for published research content.

This module adds a content-specific gate on top of the research pipeline.
It is intentionally deterministic first, with optional LLM-assisted revision
when credentials are available.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from finagent.content_automation import ContentArticlePackage
from finagent.output.compliance import is_ra_licensed, CHAT_DISCLAIMER
from finagent.runtime_provider import (
    is_content_filter_error,
    resolve_openai_config,
    resolve_openai_fallback_config,
)
logger = logging.getLogger("finagent.content.editorial")

_INTERNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bIKG\b", re.I),
    re.compile(r"\bknowledge graph\b", re.I),
    re.compile(r"\b8[- ]phase\b", re.I),
    re.compile(r"\bflash pipeline\b", re.I),
    re.compile(r"\bdeep pipeline\b", re.I),
    re.compile(r"\bAI-generated\b", re.I),
    re.compile(r"\bOpenAI\b", re.I),
    re.compile(r"\bProspektLab Knowledge Graph\b", re.I),
)

_ADVISORY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(strong buy|buy|accumulate|sell|hold|exit|target price|price target)\b", re.I),
    re.compile(r"\b(undervalued|overvalued|fairly valued)\b", re.I),
)

_GENERIC_HEADINGS = {
    "overview",
    "introduction",
    "conclusion",
    "summary",
    "key takeaways",
    "final thoughts",
}

_FILLER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bit is worth noting\b", re.I),
    re.compile(r"\bit should be noted\b", re.I),
    re.compile(r"\boverall[, ]", re.I),
    re.compile(r"\bin conclusion\b", re.I),
    re.compile(r"\bthis is important because\b", re.I),
    re.compile(r"\bneedless to say\b", re.I),
)

_SOURCE_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baccording to\b", re.I),
    re.compile(r"\bBSE\b", re.I),
    re.compile(r"\bNSE\b", re.I),
    re.compile(r"\bSEBI\b", re.I),
    re.compile(r"\bannual report\b", re.I),
    re.compile(r"\bexchange filing\b", re.I),
    re.compile(r"\bconcall\b", re.I),
    re.compile(r"\btranscript\b", re.I),
    re.compile(r"\bmanagement said\b", re.I),
)

_HIGH_URGENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(results?|earnings?|guidance|order|contract|merger|acquisition|fundraise)\b", re.I),
    re.compile(r"\b(resignation|auditor|pledge|default|forensic|insolvency|rating)\b", re.I),
    re.compile(r"\b(SEBI|regulatory|penalty|settlement|show cause|adjudication)\b", re.I),
)

_LOW_VALUE_EVENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnewspaper publication\b", re.I),
    re.compile(r"\btrading window\b", re.I),
    re.compile(r"\bcertificate under regulation\b", re.I),
    re.compile(r"\bcompliance certificate\b", re.I),
    re.compile(r"\binvestor complaints? for the quarter\b", re.I),
    re.compile(r"\bnotice of board meeting\b", re.I),
    re.compile(r"\bclosure of trading window\b", re.I),
)

_INTERNAL_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bProspektLab Knowledge Graph\b", re.I), "verified ownership and governance records"),
    (re.compile(r"\bknowledge graph\b", re.I), "ownership and governance record"),
    (re.compile(r"\bIKG\b", re.I), "verified filings"),
    (re.compile(r"\b8[- ]phase research pipeline\b", re.I), "editorial research workflow"),
    (re.compile(r"\b8[- ]phase\b", re.I), "multi-step"),
    (re.compile(r"\bflash pipeline\b", re.I), "research workflow"),
    (re.compile(r"\bdeep pipeline\b", re.I), "research workflow"),
    (re.compile(r"\bdeep[- ]dive\b", re.I), "research brief"),
    (re.compile(r"\bAI-generated\b", re.I), "researched"),
    (re.compile(r"\bOpenAI\b", re.I), "the drafting system"),
)


@dataclass
class EditorialIssue:
    code: str
    severity: str
    message: str
    location: str = ""


@dataclass
class ParagraphAudit:
    section_heading: str
    paragraph_index: int
    score: int
    issues: list[EditorialIssue] = field(default_factory=list)


@dataclass
class SectionAudit:
    heading: str
    heading_score: int
    issues: list[EditorialIssue] = field(default_factory=list)
    paragraphs: list[ParagraphAudit] = field(default_factory=list)


@dataclass
class EditorialReview:
    total_score: int
    urgency_score: int
    structure_score: int
    copy_score: int
    source_score: int
    compliance_score: int
    ready_to_publish: bool
    revision_round: int = 0
    livemint_score: int = 0
    livemint_dimensions: dict[str, float] = field(default_factory=dict)
    quality_score: int = 0
    word_count: int = 0
    substantive_section_count: int = 0
    livemint_source_violations: int = 0
    section_audits: list[SectionAudit] = field(default_factory=list)
    issues: list[EditorialIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "urgency_score": self.urgency_score,
            "structure_score": self.structure_score,
            "copy_score": self.copy_score,
            "source_score": self.source_score,
            "compliance_score": self.compliance_score,
            "livemint_score": self.livemint_score,
            "livemint_dimensions": self.livemint_dimensions,
            "quality_score": self.quality_score,
            "word_count": self.word_count,
            "substantive_section_count": self.substantive_section_count,
            "livemint_source_violations": self.livemint_source_violations,
            "ready_to_publish": self.ready_to_publish,
            "revision_round": self.revision_round,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
            "sections": [
                {
                    "heading": audit.heading,
                    "heading_score": audit.heading_score,
                    "issues": [
                        {
                            "code": issue.code,
                            "severity": issue.severity,
                            "message": issue.message,
                            "location": issue.location,
                        }
                        for issue in audit.issues
                    ],
                    "paragraphs": [
                        {
                            "paragraph_index": paragraph.paragraph_index,
                            "score": paragraph.score,
                            "issues": [
                                {
                                    "code": issue.code,
                                    "severity": issue.severity,
                                    "message": issue.message,
                                    "location": issue.location,
                                }
                                for issue in paragraph.issues
                            ],
                        }
                        for paragraph in audit.paragraphs
                    ],
                }
                for audit in self.section_audits
            ],
        }


def event_is_low_value(title: str, snippet: str = "") -> bool:
    text = f"{title} {snippet}".strip()
    return any(pattern.search(text) for pattern in _LOW_VALUE_EVENT_PATTERNS)


def contains_internal_language(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _INTERNAL_PATTERNS)


def sanitize_public_text(text: str) -> str:
    out = text or ""
    if any(token in out for token in ("Ã", "", "â")):
        try:
            repaired = out.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("�") <= out.count("�"):
                out = repaired
        except Exception:
            pass
    replacements = {
        " - ": "—",
        " - ": "–",
        "'": "'",
        "'": "'",
        """: '"',
        """: '"',
        "...": "...",
        "-": "•",
        "->": "→",
        "Rs ": "₹",
        " - ": "·",
        "+/-": "±",
        " ": " ",
        "": "",
    }
    for bad, good in replacements.items():
        out = out.replace(bad, good)
    for pattern, replacement in _INTERNAL_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s+", " ", out.replace("\xa0", " ")).strip()
    out = out.replace("verified filings record", "verified filing record")
    return out


def sanitize_public_text(text: str) -> str:
    out = text or ""
    if any(token in out for token in ("Ã", "", "â")):
        try:
            repaired = out.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("ï¿½") <= out.count("ï¿½"):
                out = repaired
        except Exception:
            pass

    replacements = {
        " - ": " - ",
        " - ": " - ",
        "Ã¢â‚¬Ëœ": "'",
        "Ã¢â‚¬â„¢": "'",
        "Ã¢â‚¬Å“": '"',
        "Ã¢â‚¬": '"',
        "Ã¢â‚¬¦": "...",
        "Ã¢â‚¬¢": " - ",
        "Ã¢â€ '": "->",
        "Rs ": "Rs ",
        "Ã‚ - ": " - ",
        "Ã‚+/-": "+/-",
        "Ã‚ ": " ",
        "Ã‚": "",
        "\u2014": " - ",
        "\u2013": " - ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2022": " - ",
        "\u2192": "->",
        "\u20b9": "Rs ",
        "\ufeff": " ",
        "\u00a0": " ",
        "": "",
    }
    for bad, good in replacements.items():
        out = out.replace(bad, good)
    for pattern, replacement in _INTERNAL_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    from finagent.content.content_accuracy import repair_replacement_chars
    out = repair_replacement_chars(out)
    out = re.sub(r"\s+", " ", out.replace("\xa0", " ")).strip()
    out = out.replace("verified filings record", "verified filing record")
    return out


def sanitize_article_package(article: ContentArticlePackage) -> ContentArticlePackage:
    data = article.model_dump()
    for key in ("title", "description", "hero_eyebrow", "hero_title", "hero_summary", "audience", "cta_label", "cta_href", "image_prompt"):
        if isinstance(data.get(key), str):
            data[key] = sanitize_public_text(str(data.get(key)))
    data["keywords"] = [sanitize_public_text(str(keyword)) for keyword in (data.get("keywords") or [])]
    for section in data.get("sections") or []:
        section["heading"] = sanitize_public_text(str(section.get("heading") or ""))
        section["paragraphs"] = [sanitize_public_text(str(paragraph)) for paragraph in (section.get("paragraphs") or [])]
        section["bullets"] = [sanitize_public_text(str(item)) for item in (section.get("bullets") or [])]
    for faq in data.get("faqs") or []:
        faq["question"] = sanitize_public_text(str(faq.get("question") or ""))
        faq["answer"] = sanitize_public_text(str(faq.get("answer") or ""))
    for takeaway in data.get("key_takeaways") or []:
        takeaway["heading"] = sanitize_public_text(str(takeaway.get("heading") or ""))
        takeaway["detail"] = sanitize_public_text(str(takeaway.get("detail") or ""))
    for metric in data.get("metrics") or []:
        metric["label"] = sanitize_public_text(str(metric.get("label") or ""))
        metric["value"] = sanitize_public_text(str(metric.get("value") or ""))
        metric["change"] = sanitize_public_text(str(metric.get("change") or ""))
        metric["period"] = sanitize_public_text(str(metric.get("period") or ""))
        metric["source"] = sanitize_public_text(str(metric.get("source") or ""))
    for table in data.get("tables") or []:
        table["title"] = sanitize_public_text(str(table.get("title") or ""))
        table["columns"] = [sanitize_public_text(str(col)) for col in (table.get("columns") or [])]
        cleaned_rows: list[list[str]] = []
        for row in table.get("rows") or []:
            if isinstance(row, list):
                cleaned_rows.append([sanitize_public_text(str(cell)) for cell in row])
        table["rows"] = cleaned_rows
        table["footnote"] = sanitize_public_text(str(table.get("footnote") or ""))
    for visual in data.get("visuals") or []:
        visual["kind"] = sanitize_public_text(str(visual.get("kind") or ""))
        visual["title"] = sanitize_public_text(str(visual.get("title") or ""))
        visual["note"] = sanitize_public_text(str(visual.get("note") or ""))
        for point in visual.get("points") or []:
            point["label"] = sanitize_public_text(str(point.get("label") or ""))
    for event in data.get("timeline") or []:
        event["date"] = sanitize_public_text(str(event.get("date") or ""))
        event["event"] = sanitize_public_text(str(event.get("event") or ""))
        event["detail"] = sanitize_public_text(str(event.get("detail") or ""))
        event["source"] = sanitize_public_text(str(event.get("source") or ""))
    for note in data.get("evidence_notes") or []:
        note["claim"] = sanitize_public_text(str(note.get("claim") or ""))
        note["source_title"] = sanitize_public_text(str(note.get("source_title") or ""))
        note["source_url"] = str(note.get("source_url") or "").strip()[:1200]
    return ContentArticlePackage.model_validate(data)


def _paragraph_review(section_heading: str, paragraph: str, paragraph_index: int) -> ParagraphAudit:
    text = (paragraph or "").strip()
    issues: list[EditorialIssue] = []
    score = 100

    if len(text) < 80:
        score -= 24
        issues.append(EditorialIssue("paragraph_too_short", "warning", "Paragraph is too short to add depth.", section_heading))
    if contains_internal_language(text):
        score -= 60
        issues.append(EditorialIssue("internal_language", "critical", "Internal system language leaked into article copy.", section_heading))
    if any(pattern.search(text) for pattern in _ADVISORY_PATTERNS):
        if is_ra_licensed():
            score -= 8
            issues.append(EditorialIssue("advisory_language", "info", "Advisory language present (RA-licensed — acceptable).", section_heading))
        else:
            score -= 65
            issues.append(EditorialIssue("advisory_language", "critical", "Advisory or valuation recommendation language detected.", section_heading))
    if any(pattern.search(text) for pattern in _FILLER_PATTERNS):
        score -= 12
        issues.append(EditorialIssue("filler_copy", "warning", "Paragraph contains filler copy instead of concrete information.", section_heading))
    if not any(pattern.search(text) for pattern in _SOURCE_SIGNAL_PATTERNS) and not re.search(r"\d", text):
        score -= 14
        issues.append(EditorialIssue("weak_grounding", "warning", "Paragraph lacks a visible source cue or concrete data point.", section_heading))

    return ParagraphAudit(section_heading=section_heading, paragraph_index=paragraph_index, score=max(0, score), issues=issues)


def _heading_review(heading: str) -> tuple[int, list[EditorialIssue]]:
    text = (heading or "").strip()
    issues: list[EditorialIssue] = []
    score = 100
    normalized = re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()

    if normalized in _GENERIC_HEADINGS:
        score -= 28
        issues.append(EditorialIssue("generic_heading", "warning", "Heading is too generic for publication.", text))
    if len(text.split()) > 12:
        score -= 12
        issues.append(EditorialIssue("long_heading", "info", "Heading is longer than necessary.", text))
    if contains_internal_language(text):
        score -= 60
        issues.append(EditorialIssue("internal_language", "critical", "Internal system language leaked into a heading.", text))

    return max(0, score), issues


def _urgency_score(article: ContentArticlePackage) -> int:
    haystack = " ".join(
        [
            article.title,
            article.description,
            article.hero_summary,
            *[section.heading for section in article.sections],
            *[paragraph for section in article.sections for paragraph in section.paragraphs],
        ]
    )
    score = 35
    for pattern in _HIGH_URGENCY_PATTERNS:
        if pattern.search(haystack):
            score += 15
    return min(score, 100)


def _count_article_words(article: ContentArticlePackage) -> int:
    chunks: list[str] = [article.title, article.description, article.hero_summary]
    for section in article.sections:
        chunks.append(section.heading)
        chunks.extend(section.paragraphs)
        chunks.extend(section.bullets)
    for takeaway in article.key_takeaways:
        chunks.append(takeaway.heading)
        chunks.append(takeaway.detail)
    for faq in article.faqs:
        chunks.append(faq.question)
        chunks.append(faq.answer)
    return len(re.findall(r"\b[\w%-]+\b", " ".join(chunks)))


def _count_substantive_sections(article: ContentArticlePackage) -> int:
    count = 0
    for section in article.sections:
        para_words = sum(len(re.findall(r"\b[\w%-]+\b", p)) for p in section.paragraphs)
        bullet_words = sum(len(re.findall(r"\b[\w%-]+\b", b)) for b in section.bullets)
        if len(section.paragraphs) >= 2 and (para_words + bullet_words) >= 55:
            count += 1
    return count


def review_article_package(
    article: ContentArticlePackage,
    *,
    revision_round: int = 0,
    is_official_source: bool = False,
    quality_score: int = 0,
    evidence_claim_count: int | None = None,
    livemint_source_violations: int = 0,
    source_material: str = "",
    archetype: str = "",
) -> EditorialReview:
    article = sanitize_article_package(article)
    issues: list[EditorialIssue] = []
    section_audits: list[SectionAudit] = []

    heading_scores: list[int] = []
    paragraph_scores: list[int] = []
    paragraphs_with_source_signal = 0

    for section in article.sections:
        heading_score, heading_issues = _heading_review(section.heading)
        heading_scores.append(heading_score)
        section_audit = SectionAudit(heading=section.heading, heading_score=heading_score, issues=list(heading_issues))
        issues.extend(heading_issues)

        for idx, paragraph in enumerate(section.paragraphs, start=1):
            paragraph_audit = _paragraph_review(section.heading, paragraph, idx)
            section_audit.paragraphs.append(paragraph_audit)
            paragraph_scores.append(paragraph_audit.score)
            issues.extend(paragraph_audit.issues)
            if any(pattern.search(paragraph) for pattern in _SOURCE_SIGNAL_PATTERNS) or re.search(r"\d", paragraph):
                paragraphs_with_source_signal += 1

        section_audits.append(section_audit)

    word_count = _count_article_words(article)
    substantive_count = _count_substantive_sections(article)

    if substantive_count < 6:
        issues.append(EditorialIssue(
            "insufficient_substantive_sections",
            "critical",
            f"Article has {substantive_count} substantive sections; minimum is 6.",
            "article",
        ))
    elif len(article.sections) < 6:
        issues.append(EditorialIssue("shallow_structure", "warning", "Article needs more sections for deep research depth.", "article"))
    if is_official_source and word_count < 900:
        issues.append(EditorialIssue(
            "official_article_too_short",
            "critical",
            f"Official-source story has {word_count} words; minimum is 900.",
            "article",
        ))
    if evidence_claim_count is not None and evidence_claim_count <= 0:
        issues.append(EditorialIssue(
            "missing_evidence_claims",
            "critical",
            "Article has no attributed evidence claims.",
            "evidence",
        ))
    if livemint_source_violations > 0:
        issues.append(EditorialIssue(
            "livemint_source_leak",
            "critical",
            f"{livemint_source_violations} Livemint URL(s) reached the evidence pack.",
            "sources",
        ))
    if len(article.faqs) < 4:
        issues.append(EditorialIssue("light_faq", "info", "Article should answer more reader questions.", "faq"))
    if len(article.key_takeaways) < 4:
        issues.append(EditorialIssue("light_takeaways", "warning", "Article needs at least four key takeaways.", "takeaways"))
    if contains_internal_language(article.description) or contains_internal_language(article.hero_summary):
        issues.append(EditorialIssue("internal_language", "critical", "Internal system language leaked into article metadata.", "meta"))

    # ── Accuracy guards ──────────────────────────────────────────────────────
    from finagent.content.content_accuracy import (
        suspect_evidence_urls,
        ungrounded_headline_numbers,
        visual_issues,
    )

    # (a) Headline numbers must trace to a sourced claim or supplied material —
    #     not to the model's own free prose or self-asserted metric blocks.
    grounded_text = " ".join(
        [str(n.claim or "") for n in article.evidence_notes]
        + [str(getattr(ev, "date", "")) + " " + str(getattr(ev, "event", "")) + " " + str(getattr(ev, "detail", "")) for ev in article.timeline]
        + ([source_material] if source_material else [])
    )
    if archetype:
        # Archetype-aware anchoring: a title must carry a GROUNDED, specific
        # anchor of its story type (a grounded number for earnings/rating/M&A, a
        # role+action for personnel, a regulator+action for regulatory, a
        # concrete subject for trend/company). Catches vague number-free titles
        # the numbers-only check rewards. A failure blocks publish (critical),
        # same handling as the ungrounded_headline_number issue.
        from finagent.content.archetype import title_anchor_ok

        anchor_ok, reason_code = title_anchor_ok(article.title, archetype, grounded_text)
        if not anchor_ok:
            issues.append(EditorialIssue(
                "ungrounded_headline_number",
                "critical",
                f"Headline lacks a grounded {archetype} anchor ({reason_code}).",
                "title",
            ))
    else:
        # Backward-compatible default: numbers-only headline grounding check.
        ungrounded = ungrounded_headline_numbers(article.title, grounded_text)
        if ungrounded:
            issues.append(EditorialIssue(
                "ungrounded_headline_number",
                "critical",
                f"Headline stat(s) {', '.join(ungrounded)} not backed by any sourced evidence claim.",
                "title",
            ))

    # (b) Logically broken visuals (placeholder/illustrative/single-value charts).
    for idx, visual in enumerate(article.visuals):
        v_issues = visual_issues(visual)
        if v_issues:
            issues.append(EditorialIssue(
                "broken_visual",
                "critical",
                f"Visual '{getattr(visual, 'title', '')}' is not a trustworthy data chart: {', '.join(v_issues)}.",
                f"visual[{idx}]",
            ))

    # (c) Fabricated source URLs in evidence notes.
    fake_urls = suspect_evidence_urls(article.evidence_notes)
    if fake_urls:
        issues.append(EditorialIssue(
            "fabricated_source_url",
            "critical",
            f"{len(fake_urls)} evidence note URL(s) look fabricated (e.g. {fake_urls[0][:80]}).",
            "evidence",
        ))

    structure_score = int((sum(heading_scores) / max(1, len(heading_scores))) * 0.45 + min(len(article.sections), 8) / 8 * 55)
    copy_score = int(sum(paragraph_scores) / max(1, len(paragraph_scores)))
    source_score = min(100, int((paragraphs_with_source_signal / max(1, len(paragraph_scores))) * 100))
    compliance_score = 100
    if any(issue.code == "internal_language" for issue in issues):
        compliance_score -= 45
    if any(issue.code == "advisory_language" for issue in issues):
        compliance_score -= 10 if is_ra_licensed() else 55
    if any(issue.code == "livemint_source_leak" for issue in issues):
        compliance_score -= 45
    compliance_score = max(0, compliance_score)
    urgency_score = _urgency_score(article)

    # LiveMint-style narrative journalism dimension.
    from finagent.content.livemint_editorial import PASS_THRESHOLD, evaluate_livemint_quality
    lm = evaluate_livemint_quality(article.model_dump())
    livemint_score = int(round(lm["score"]))
    if not lm["passed"]:
        issues.append(EditorialIssue(
            "weak_narrative_journalism", "warning",
            "Article does not yet read like LiveMint-grade journalism: "
            + "; ".join(lm["revision_guidance"][:6]),
            "narrative",
        ))

    total_score = int(round(
        structure_score * 0.20 +
        copy_score * 0.24 +
        source_score * 0.18 +
        compliance_score * 0.18 +
        urgency_score * 0.05 +
        livemint_score * 0.15
    ))
    has_critical = any(issue.severity == "critical" for issue in issues)
    # Gate now also requires LiveMint editorial quality to pass.
    ready_to_publish = (
        total_score >= 85
        and urgency_score >= 50
        and livemint_score >= int(PASS_THRESHOLD)
        and not has_critical
    )

    return EditorialReview(
        total_score=total_score,
        urgency_score=urgency_score,
        structure_score=structure_score,
        copy_score=copy_score,
        source_score=source_score,
        compliance_score=compliance_score,
        livemint_score=livemint_score,
        livemint_dimensions=lm["dimensions"],
        quality_score=max(0, min(int(quality_score), 100)),
        word_count=word_count,
        substantive_section_count=substantive_count,
        livemint_source_violations=max(0, int(livemint_source_violations)),
        ready_to_publish=ready_to_publish,
        revision_round=revision_round,
        section_audits=section_audits,
        issues=issues,
    )


async def _llm_critique_article(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
) -> str:
    """Financial-editor critique: structured feedback on narrative, data density, and rhythm."""
    llm_cfg = resolve_openai_config(complexity="moderate")
    if llm_cfg is None:
        return ""

    try:
        from openai import AsyncOpenAI
    except Exception:
        return ""

    system_prompt = (
        "You are a senior markets correspondent and financial editor at a top Indian business daily "
        "(think LiveMint or Hindu BusinessLine). You are critiquing an article before publication.\n\n"
        "Evaluate on these dimensions and give specific, actionable feedback:\n"
        "1. **Lede strength**: Does the opening grab with stakes, not throat-clearing?\n"
        "2. **'Why now' clarity**: Is the timing/catalyst for this story made explicit in the first 2 paragraphs?\n"
        "3. **Context depth**: Are there historical comparisons, sector benchmarks, or policy context?\n"
        "4. **Data density**: Are concrete numbers (revenue, margins, ratios) present and attributed?\n"
        "5. **Narrative arc**: Does the article flow from hook → context → evidence → implications → outlook?\n"
        "6. **Rhythm & readability**: Mix of sentence lengths? No repetitive structure?\n"
        "7. **Jargon & filler**: Any vague phrases ('significant growth', 'strong performance') without specifics?\n\n"
        "Return a JSON object: {\"score\": 0-100, \"strengths\": [\"...\"], \"weaknesses\": [\"...\"], \"rewrites\": [\"section heading: specific instruction\"]}"
    )
    user_prompt = (
        f"Topic: {target}\n\n"
        f"Title: {article.title}\n"
        f"Description: {article.description}\n\n"
    )
    for section in article.sections[:10]:
        user_prompt += f"## {section.heading}\n" + "\n".join(section.paragraphs[:6]) + "\n\n"

    async def _call(cfg: Any) -> str:
        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        response = await client.chat.completions.create(
            model=os.getenv("FINAGENT_EDITORIAL_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or cfg.model or "gpt-5.4-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_completion_tokens=1200,
            response_format={"type": "json_object"},
            timeout=45,
        )
        return (response.choices[0].message.content or "").strip()

    try:
        return await _call(llm_cfg)
    except Exception as exc:
        if is_content_filter_error(exc):
            fb = resolve_openai_fallback_config(complexity="moderate")
            if fb is not None:
                try:
                    return await _call(fb)
                except Exception as fb_exc:
                    logger.warning("Editorial critique fallback failed: %s", fb_exc)
                    return ""
        logger.warning("Editorial critique failed: %s", exc)
        return ""


async def _llm_revise_article(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
    critique_feedback: str = "",
) -> ContentArticlePackage | None:
    llm_cfg = resolve_openai_config(complexity="moderate")
    if llm_cfg is None:
        return None

    try:
        from openai import AsyncOpenAI
    except Exception:
        return None

    issue_lines = "\n".join(f"- {issue.code}: {issue.message} ({issue.location})" for issue in review.issues[:18])
    advisory_instruction = "" if is_ra_licensed() else (
        " Keep the tone analytical and neutral; describe what filings disclose rather than offering an investment recommendation."
    )
    system_prompt = (
        "You are a senior markets correspondent at a top Indian business daily. "
        "Rewrite the article for publication with the following voice:\n"
        "- Open with stakes: the lede should make clear why the disclosure matters right now.\n"
        "- Include at least one historical comparison or sector benchmark per substantive section.\n"
        "- Attribute sentiment to its source (for example, the company's commentary, analyst notes, or filings) rather than asserting unattributed opinion.\n"
        "- Close with a forward-looking line: upcoming catalysts, next data point, what to watch.\n"
        "- Replace vague descriptors with specific numbers and named entities.\n"
        "- Use editorial language only; do not reference internal tools or workflow steps."
        f"{advisory_instruction}\n"
        "Return only valid JSON matching the ContentArticlePackage schema."
    )
    critique_block = ""
    if critique_feedback:
        critique_block = f"\n\nEditor critique (address these):\n{critique_feedback}\n"
    user_prompt = (
        f"Rewrite this article for publication on the topic '{target}'.\n"
        f"Fix every editorial issue below while preserving factual claims.{critique_block}\n\n"
        f"Editorial issues:\n{issue_lines}\n\n"
        f"Current article JSON:\n{json.dumps(article.model_dump(), ensure_ascii=True)}\n\n"
        "Return only the corrected JSON object."
    )

    async def _call(cfg: Any) -> ContentArticlePackage | None:
        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        response = await client.chat.completions.create(
            model=os.getenv("FINAGENT_EDITORIAL_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or cfg.model or "gpt-5.4-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_completion_tokens=7000,
            response_format={"type": "json_object"},
            timeout=90,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\n?```$", "", raw)
        return ContentArticlePackage.model_validate(json.loads(raw))

    try:
        return await _call(llm_cfg)
    except Exception as exc:
        if is_content_filter_error(exc):
            fb = resolve_openai_fallback_config(complexity="moderate")
            if fb is not None:
                try:
                    return await _call(fb)
                except Exception as fb_exc:
                    logger.warning("Editorial LLM revision fallback failed: %s", fb_exc)
                    return None
        logger.warning("Editorial LLM revision failed: %s", exc)
        return None


async def revise_article_package(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
    critique_feedback: str = "",
) -> ContentArticlePackage:
    revised = await _llm_revise_article(article, review, target=target, critique_feedback=critique_feedback)
    if revised is not None:
        return sanitize_article_package(revised)
    return sanitize_article_package(article)


async def run_editorial_revision_loop(
    article: ContentArticlePackage,
    *,
    target: str,
    max_rounds: int = 3,
    is_official_source: bool = False,
    quality_score: int = 0,
    evidence_claim_count: int | None = None,
    livemint_source_violations: int = 0,
    source_material: str = "",
    archetype: str = "",
) -> tuple[ContentArticlePackage, EditorialReview]:
    current = sanitize_article_package(article)
    review_ctx = dict(
        is_official_source=is_official_source,
        quality_score=quality_score,
        evidence_claim_count=evidence_claim_count,
        livemint_source_violations=livemint_source_violations,
        source_material=source_material,
        archetype=archetype,
    )
    review = review_article_package(current, revision_round=0, **review_ctx)
    for round_index in range(1, max_rounds + 1):
        if review.ready_to_publish:
            break
        critique_feedback = ""
        if round_index <= 2:
            critique_feedback = await _llm_critique_article(current, review, target=target)
            if critique_feedback:
                logger.info("[EDITORIAL] critique round %d score feedback received (%d chars)", round_index, len(critique_feedback))
        current = await revise_article_package(current, review, target=target, critique_feedback=critique_feedback)
        review = review_article_package(current, revision_round=round_index, **review_ctx)
    return current, review
