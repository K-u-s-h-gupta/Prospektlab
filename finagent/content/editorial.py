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
from finagent.runtime_provider import resolve_openai_config
logger = logging.getLogger("finagent.content.editorial")

_INTERNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bIKG\b", re.I),
    re.compile(r"\bknowledge graph\b", re.I),
    re.compile(r"\b8[- ]phase\b", re.I),
    re.compile(r"\bflash pipeline\b", re.I),
    re.compile(r"\bdeep pipeline\b", re.I),
    re.compile(r"\bresearch pipeline\b", re.I),
    re.compile(r"\bcontent pipeline\b", re.I),
    re.compile(r"\bAI-generated\b", re.I),
    re.compile(r"\bOpenAI\b", re.I),
    re.compile(r"\bProspektLab Knowledge Graph\b", re.I),
    re.compile(r"\bContentArticlePackage\b", re.I),
    re.compile(r"\bContentArticlePackage schema\b", re.I),
    re.compile(r"\bJSON schema\b", re.I),
    re.compile(r"\bReturn only valid JSON\b", re.I),
    re.compile(r"\bReturn ONLY valid JSON\b", re.I),
    re.compile(r"\bNEWSROOM ARTICLE SYNTHESIS\b", re.I),
    re.compile(r"\bFinal synthesis\b", re.I),
    re.compile(r"\bSession ID\b", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\buser prompt\b", re.I),
    re.compile(r"\blanguage model\b", re.I),
    re.compile(r"\bquality score\b", re.I),
    re.compile(r"\bcoverage score\b", re.I),
    re.compile(r"\bresearch run\b", re.I),
    re.compile(r"\bdata gaps?\b", re.I),
    re.compile(r"\bevidence quality\b", re.I),
    re.compile(r"\bthin evidence\b", re.I),
    re.compile(r"\bTier-1 citations?\b", re.I),
    re.compile(r"\bno financial metrics resolved\b", re.I),
    re.compile(r"\bdid not retrieve financial data\b", re.I),
    re.compile(r"\bspecialist findings?\b", re.I),
    re.compile(r"\bconflicts? detected\b", re.I),
    re.compile(r"\bsources processed\b", re.I),
    re.compile(r"\bthis article was generated\b", re.I),
    re.compile(r"\bgenerated article\b", re.I),
    re.compile(r"\bworking research query\b", re.I),
    re.compile(r"\bnext editorial pass\b", re.I),
    re.compile(r"\bin this article\b", re.I),
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
    re.compile(r"\btax deduction on dividend\b", re.I),
    re.compile(r"\bTDS on dividend\b", re.I),
)

_INTERNAL_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bProspektLab Knowledge Graph\b", re.I), "verified ownership and governance records"),
    (re.compile(r"\bknowledge graph\b", re.I), "ownership and governance record"),
    (re.compile(r"\bIKG\b", re.I), "verified filings"),
    (re.compile(r"\b8[- ]phase research pipeline\b", re.I), "editorial research workflow"),
    (re.compile(r"\b8[- ]phase\b", re.I), "multi-step"),
    (re.compile(r"\bflash pipeline\b", re.I), "research workflow"),
    (re.compile(r"\bdeep pipeline\b", re.I), "research workflow"),
    (re.compile(r"\bresearch pipeline\b", re.I), "research process"),
    (re.compile(r"\bcontent pipeline\b", re.I), "publishing process"),
    (re.compile(r"\bdeep[- ]dive\b", re.I), "research brief"),
    (re.compile(r"\bAI-generated\b", re.I), "researched"),
    (re.compile(r"\bOpenAI\b", re.I), "the drafting system"),
    (re.compile(r"\bContentArticlePackage\b", re.I), "article"),
    (re.compile(r"\bContentArticlePackage schema\b", re.I), "article format"),
    (re.compile(r"\bJSON schema\b", re.I), "article format"),
    (re.compile(r"\bReturn only valid JSON\b", re.I), "Use a clean article format"),
    (re.compile(r"\bReturn ONLY valid JSON\b", re.I), "Use a clean article format"),
    (re.compile(r"\bNEWSROOM ARTICLE SYNTHESIS\b", re.I), "financial news explainer"),
    (re.compile(r"\bFinal synthesis\b", re.I), "editorial synthesis"),
    (re.compile(r"\bSession ID\b", re.I), "reference"),
    (re.compile(r"\bsystem prompt\b", re.I), "editorial brief"),
    (re.compile(r"\buser prompt\b", re.I), "editorial brief"),
    (re.compile(r"\blanguage model\b", re.I), "drafting system"),
    (re.compile(r"\bquality score\b", re.I), "editorial confidence"),
    (re.compile(r"\bcoverage score\b", re.I), "source coverage"),
    (re.compile(r"\bresearch run\b", re.I), "public records reviewed"),
    (re.compile(r"\bdata gaps?\b", re.I), "available-data limitations"),
    (re.compile(r"\bevidence quality\b", re.I), "source depth"),
    (re.compile(r"\bthin evidence\b", re.I), "limited source depth"),
    (re.compile(r"\bTier-1 citations?\b", re.I), "primary-source references"),
    (re.compile(r"\bno financial metrics resolved\b", re.I), "financial metrics were not available in the reviewed source packet"),
    (re.compile(r"\bdid not retrieve financial data\b", re.I), "did not include financial data in the reviewed source packet"),
    (re.compile(r"\bspecialist findings?\b", re.I), "research notes"),
    (re.compile(r"\bconflicts? detected\b", re.I), "conflicting evidence"),
    (re.compile(r"\bsources processed\b", re.I), "sources reviewed"),
    (re.compile(r"\bthis article was generated\b", re.I), "this article was prepared"),
    (re.compile(r"\bgenerated article\b", re.I), "published article"),
    (re.compile(r"\bworking research query\b", re.I), "research topic"),
    (re.compile(r"\bnext editorial pass\b", re.I), "next review"),
    (re.compile(r"\bin this article\b", re.I), "below"),
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
    raw_text = " ".join(
        [
            article.title,
            article.description,
            article.hero_eyebrow,
            article.hero_title,
            article.hero_summary,
            *[section.heading for section in article.sections],
            *[paragraph for section in article.sections for paragraph in section.paragraphs],
            *[bullet for section in article.sections for bullet in section.bullets],
            *[faq.question for faq in article.faqs],
            *[faq.answer for faq in article.faqs],
        ]
    )
    had_internal_language = contains_internal_language(raw_text)
    article = sanitize_article_package(article)
    issues: list[EditorialIssue] = []
    section_audits: list[SectionAudit] = []

    if had_internal_language:
        issues.append(
            EditorialIssue(
                "internal_language",
                "critical",
                "Drafting-process language was present before public-copy sanitization.",
                "article",
            )
        )

    heading_scores: list[int] = []
    paragraph_scores: list[int] = []
    paragraphs_with_source_signal = 0
    article_word_count = len(re.findall(r"\b[\w'-]+\b", raw_text))
    body_paragraph_count = sum(len(section.paragraphs) for section in article.sections)

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

    if len(article.sections) < 10:
        issues.append(EditorialIssue("shallow_structure", "critical", "Article needs at least 10 sections for newsroom depth.", "article"))
    if body_paragraph_count < 18:
        issues.append(EditorialIssue("thin_paragraph_depth", "critical", "Article needs at least 18 body paragraphs for newsroom depth.", "article"))
    if article_word_count < 1200:
        issues.append(EditorialIssue("short_depth", "critical", "Article needs at least 1,200 words before publication.", "article"))
    elif article_word_count < 1600:
        issues.append(EditorialIssue("short_depth", "warning", "Article should be expanded toward 1,600+ words for investor-grade depth.", "article"))
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
    ready_to_publish = total_score >= 84 and urgency_score >= 45 and not has_critical

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


def _public_revision_note(issue: EditorialIssue) -> str:
    if issue.code == "short_depth":
        return "Expand the article with source-backed context, history, investor implications, risks, and watchpoints until it reaches newsroom depth."
    if issue.code == "shallow_structure":
        return "Add more focused sections so the article has a full newsroom arc, not a short summary."
    if issue.code == "thin_paragraph_depth":
        return "Add more body paragraphs with concrete facts, source cues, and practical implications for Indian investors."
    if issue.code == "internal_language":
        return f"Use reader-facing wording in {issue.location}; replace process vocabulary with plain market context."
    if issue.code == "advisory_language":
        return f"Use neutral investor education language in {issue.location}; avoid investment calls or valuation labels."
    if issue.code == "weak_grounding":
        return f"Add a source cue, date, number, or clearly labelled watchpoint in {issue.location}."
    if issue.code == "paragraph_too_short":
        return f"Expand {issue.location} with concrete context, implications, and investor checklist detail."
    if issue.code == "filler_copy":
        return f"Replace generic phrasing in {issue.location} with specific facts and portfolio implications."
    if issue.code == "generic_heading":
        return f"Make the heading more specific: {issue.location}."
    if issue.code == "shallow_structure":
        return "Add enough section depth for a complete investor briefing."
    if issue.code == "light_faq":
        return "Add practical investor questions and concise answers."
    return f"Improve {issue.location or 'the article'} for publication quality."


async def _llm_revise_article(
    article: ContentArticlePackage,
    review: EditorialReview,
    *,
    target: str,
) -> ContentArticlePackage | None:
    cfg = resolve_openai_config()
    if cfg is None:
        return None

    try:
        from openai import AsyncOpenAI
    except Exception:
        return None

    issue_lines = "\n".join(f"- {_public_revision_note(issue)}" for issue in review.issues[:18])
    system_prompt = (
        "You are a senior financial editor preparing an investor article for publication. "
        "Respond with one JSON object using the same article fields supplied by the input. "
        "Use reader-facing editorial language, neutral investor education wording, and source-grounded claims."
    )
    user_prompt = (
        f"Prepare the article for publication on the topic '{target}'.\n"
        "Keep factual claims intact unless the article itself provides support for a clearer phrasing.\n"
        "Use these editing notes:\n"
        f"{issue_lines}\n\n"
        f"Article data:\n{json.dumps(article.model_dump(), ensure_ascii=True)}\n\n"
        "Respond with the corrected JSON object."
    )

    try:
        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        response = await client.chat.completions.create(
            model=os.getenv("FINAGENT_EDITORIAL_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or cfg.model,
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
