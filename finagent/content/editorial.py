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
    if any(token in out for token in ("Ã", "Â", "â")):
        try:
            repaired = out.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("�") <= out.count("�"):
                out = repaired
        except Exception:
            pass
    replacements = {
        "â€”": "—",
        "â€“": "–",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€¦": "...",
        "â€¢": "•",
        "â†’": "→",
        "â‚¹": "₹",
        "Â·": "·",
        "Â±": "±",
        "Â ": " ",
        "Â": "",
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
    if any(token in out for token in ("Ã", "Â", "â")):
        try:
            repaired = out.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("ï¿½") <= out.count("ï¿½"):
                out = repaired
        except Exception:
            pass

    replacements = {
        "Ã¢â‚¬â€": " - ",
        "Ã¢â‚¬â€œ": " - ",
        "Ã¢â‚¬Ëœ": "'",
        "Ã¢â‚¬â„¢": "'",
        "Ã¢â‚¬Å“": '"',
        "Ã¢â‚¬Â": '"',
        "Ã¢â‚¬Â¦": "...",
        "Ã¢â‚¬Â¢": " - ",
        "Ã¢â€ â€™": "->",
        "Ã¢â€šÂ¹": "Rs ",
        "Ã‚Â·": " - ",
        "Ã‚Â±": "+/-",
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
        "Â": "",
    }
    for bad, good in replacements.items():
        out = out.replace(bad, good)
    for pattern, replacement in _INTERNAL_REPLACEMENTS:
        out = pattern.sub(replacement, out)
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


def review_article_package(article: ContentArticlePackage, *, revision_round: int = 0) -> EditorialReview:
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

    if len(article.sections) < 6:
        issues.append(EditorialIssue("shallow_structure", "warning", "Article needs more sections for deep research depth.", "article"))
    if len(article.faqs) < 4:
        issues.append(EditorialIssue("light_faq", "info", "Article should answer more reader questions.", "faq"))
    if contains_internal_language(article.description) or contains_internal_language(article.hero_summary):
        issues.append(EditorialIssue("internal_language", "critical", "Internal system language leaked into article metadata.", "meta"))

    structure_score = int((sum(heading_scores) / max(1, len(heading_scores))) * 0.45 + min(len(article.sections), 8) / 8 * 55)
    copy_score = int(sum(paragraph_scores) / max(1, len(paragraph_scores)))
    source_score = min(100, int((paragraphs_with_source_signal / max(1, len(paragraph_scores))) * 100))
    compliance_score = 100
    if any(issue.code == "internal_language" for issue in issues):
        compliance_score -= 45
    if any(issue.code == "advisory_language" for issue in issues):
        compliance_score -= 55
    compliance_score = max(0, compliance_score)
    urgency_score = _urgency_score(article)

    total_score = int(round(
        structure_score * 0.22 +
        copy_score * 0.28 +
        source_score * 0.22 +
        compliance_score * 0.20 +
        urgency_score * 0.08
    ))
    has_critical = any(issue.severity == "critical" for issue in issues)
    ready_to_publish = total_score >= 90 and urgency_score >= 50 and not has_critical

    return EditorialReview(
        total_score=total_score,
        urgency_score=urgency_score,
        structure_score=structure_score,
        copy_score=copy_score,
        source_score=source_score,
        compliance_score=compliance_score,
        ready_to_publish=ready_to_publish,
        revision_round=revision_round,
        section_audits=section_audits,
        issues=issues,
    )


async def _llm_revise_article(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
) -> ContentArticlePackage | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import AsyncOpenAI
    except Exception:
        return None

    issue_lines = "\n".join(f"- {issue.code}: {issue.message} ({issue.location})" for issue in review.issues[:18])
    system_prompt = (
        "You are a senior financial editor rewriting an article for publication. "
        "Return only valid JSON matching the ContentArticlePackage schema. "
        "Do not mention internal systems, AI, pipelines, or knowledge graphs. "
        "Do not use buy, sell, hold, target price, undervalued, or overvalued language."
    )
    user_prompt = (
        f"Rewrite this article for publication on the topic '{target}'.\n"
        f"Fix every issue below while preserving factual claims.\n\n"
        f"Editorial issues:\n{issue_lines}\n\n"
        f"Current article JSON:\n{json.dumps(article.model_dump(), ensure_ascii=True)}\n\n"
        "Return only the corrected JSON object."
    )

    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=os.getenv("FINAGENT_EDITORIAL_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=4000,
            response_format={"type": "json_object"},
            timeout=60,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\n?```$", "", raw)
        return ContentArticlePackage.model_validate(json.loads(raw))
    except Exception as exc:
        logger.warning("Editorial LLM revision failed: %s", exc)
        return None


async def revise_article_package(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
) -> ContentArticlePackage:
    revised = await _llm_revise_article(article, review, target=target)
    if revised is not None:
        return sanitize_article_package(revised)
    return sanitize_article_package(article)


async def run_editorial_revision_loop(
    article: ContentArticlePackage,
    *,
    target: str,
    max_rounds: int = 3,
) -> tuple[ContentArticlePackage, EditorialReview]:
    current = sanitize_article_package(article)
    review = review_article_package(current, revision_round=0)
    for round_index in range(1, max_rounds + 1):
        if review.ready_to_publish:
            break
        current = await revise_article_package(current, review, target=target)
        review = review_article_package(current, revision_round=round_index)
    return current, review
