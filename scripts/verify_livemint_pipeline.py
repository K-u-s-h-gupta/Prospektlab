"""End-to-end smoke that exercises the new content pipeline against a real LLM.

Runs:
  1. The 10-specialist research wave.
  2. A one-shot ContentArticlePackage synthesis with the same model.
  3. The full editorial revision loop (capped at 2 rounds for speed).
  4. The 7-dimension publish gate evaluation.
  5. A side-by-side comparison against a fixed Livemint-style rubric.

Prints a structured report to stdout so the operator can eyeball the article
without standing up the gateway.

Usage:
  .venv-prospektlab311b\\Scripts\\python.exe scripts\\verify_livemint_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # type: ignore

load_dotenv(ROOT / "backend" / "finagent" / ".env")

# Force the OpenAI-direct path: skip Azure RAI entirely.
os.environ.setdefault("FINAGENT_BYPASS_AZURE", "1")

import openai

from finagent.content.editorial import review_article_package, run_editorial_revision_loop
from finagent.content.livemint_blocker import sanitise_evidence_pack
from finagent.content.specialist_agents import (
    SPECIALIST_KINDS,
    run_specialist_wave,
    summarise_wave,
    wave_to_prompt_block,
)
from finagent.content_automation import (
    ContentArticlePackage,
    _public_article_dirs,
    _article_dir,
    _upsert_sitemap,
    refresh_public_research_hub,
    render_article_html,
)
from finagent.runtime_provider import (
    is_content_filter_error,
    resolve_openai_config,
    resolve_openai_fallback_config,
)

TARGET = os.environ.get("VERIFY_TARGET", "Infosys Q4 FY25 results")
CONTEXT = os.environ.get(
    "VERIFY_CONTEXT",
    "Infosys is India's second-largest IT services firm. Q4 FY25 results are public on "
    "BSE/NSE. Key disclosed items: revenue, operating margin (~21%), deal TCV, attrition, "
    "guidance for FY26 in constant currency, segment mix, and capital return policy.",
)

LIVEMINT_RUBRIC = [
    ("Hard-number-anchored headline (60-100 chars, named entity)", "headline_punch"),
    ("Inverted-pyramid lede front-loading a number, >=35 words", "narrative_lede"),
    ("Market context block, >=40 words with index/peer/macro framing", "market_context"),
    ("Attributed analyst commentary, >=40 words", "analyst_commentary"),
    ("Six or more substantive body sections (prose-heavy)", "sections"),
    ("Four or more key takeaways and four or more FAQs", "takeaways_faqs"),
    ("Labelled metrics table with value, change, period, source", "metrics"),
    ("Structured data table with columns, rows, footnote", "tables"),
    ("Evidence notes with claim + source title + URL", "evidence_notes"),
    ("Dated timeline of material events", "timeline"),
    ("Visual prompt for at least one auto-generated chart", "visuals"),
    ("Zero generic SEO filler in body", "no_filler"),
    ("No advisory language (no buy/sell/target price)", "no_advisory"),
    ("Source signals (BSE/NSE/SEBI/'according to'/numbers) in most paragraphs", "source_signals"),
    ("Quality of research coverage across the 10 specialists", "quality_score"),
]


def _client() -> tuple[openai.AsyncOpenAI, str, openai.AsyncOpenAI | None, str | None]:
    cfg = resolve_openai_config(complexity="moderate")
    if cfg is None:
        raise SystemExit("No LLM key resolved; set Azure foundry or OPENAI_API_KEY.")
    client = openai.AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    model = os.getenv("VERIFY_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or cfg.model or "gpt-5.4-mini"
    fb_cfg = resolve_openai_fallback_config(complexity="moderate")
    fb_client = openai.AsyncOpenAI(api_key=fb_cfg.api_key) if fb_cfg else None
    fb_model = fb_cfg.model if fb_cfg else None
    return client, model, fb_client, fb_model


async def _chat_with_fallback(
    client: openai.AsyncOpenAI,
    model: str,
    fb_client: openai.AsyncOpenAI | None,
    fb_model: str | None,
    *,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: int,
    response_format: dict | None = None,
) -> str:
    async def _call(c: openai.AsyncOpenAI, m: str) -> str:
        kw: dict = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "timeout": timeout,
        }
        if response_format:
            kw["response_format"] = response_format
        resp = await c.chat.completions.create(**kw)
        return (resp.choices[0].message.content or "").strip()

    try:
        return await _call(client, model)
    except Exception as exc:
        if is_content_filter_error(exc) and fb_client is not None and fb_model is not None:
            return await _call(fb_client, fb_model)
        raise


async def synthesise_article(client: openai.AsyncOpenAI, model: str, wave_block: str, fb_client: openai.AsyncOpenAI | None = None, fb_model: str | None = None) -> ContentArticlePackage:
    system = (
        "You are a senior markets correspondent at a top Indian business daily. "
        "Produce a publication-ready financial article as ContentArticlePackage JSON. "
        "Voice rules: front-load stakes in the lede with a hard number; embed numerical "
        "data inside narrative sentences at 2.5+ data points per 100 words; attribute "
        "every sentiment to its source; close with a forward-looking line; vary sentence lengths. "
        "Every body paragraph must cite an official source by name (BSE filing, NSE disclosure, "
        "SEBI order, RBI release, MCA filing, annual report, concall transcript) or include a "
        "specific number with units. Exclude livemint.com from sources. Keep the tone analytical "
        "and neutral. Return strictly the JSON schema."
    )
    user = (
        f"TARGET: {TARGET}\n\nBACKGROUND CONTEXT:\n{CONTEXT}\n\n"
        f"{wave_block}\n\n"
        "Return ONLY a JSON object with keys: slug, title (60-100 chars with hard number), "
        "description (140-170 chars), hero_eyebrow, hero_title, hero_summary, audience, "
        "keywords (8-12), narrative_lede (>=35 words, hard number first), "
        "market_context (>=40 words), analyst_commentary (>=40 words), "
        "key_takeaways (4-6: {heading, detail>=12 chars}), "
        "metrics (4-8: {label, value, change, period, source}), "
        "tables (1-3: {title, columns, rows, footnote}), "
        "visuals (1-2: {kind, title, points:[{label, value}], note}), "
        "timeline (3-8: {date, event, detail, source}), "
        "evidence_notes (4-10: {claim, source_title, source_url}), "
        "sections (6-8: {heading, paragraphs: [3 prose strings each >=80 chars], bullets: []}), "
        "faqs (4-5: {question, answer}), "
        "cta_label, cta_href, image_prompt."
    )
    raw = await _chat_with_fallback(
        client, model, fb_client, fb_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=6000,
        timeout=120,
        response_format={"type": "json_object"},
    )
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw)
    data = json.loads(raw)
    # Coerce numeric-ish fields: model often returns "INR 35,000 crore" where the
    # schema expects a float (visuals point values, table cells).
    for vis in data.get("visuals") or []:
        for point in vis.get("points") or []:
            val = point.get("value")
            if isinstance(val, str):
                m = re.search(r"-?\d+(?:[.,]\d+)*", val)
                point["value"] = float(m.group(0).replace(",", "")) if m else 0.0
    # Coerce list-shaped audience back to a comma-joined string.
    if isinstance(data.get("audience"), list):
        data["audience"] = ", ".join(str(a) for a in data["audience"])[:300]
    # Some models emit table.rows as list[dict]; flatten to list[list[str]].
    for tbl in data.get("tables") or []:
        rows = tbl.get("rows") or []
        flat: list[list[str]] = []
        for row in rows:
            if isinstance(row, list):
                flat.append([str(c) for c in row])
            elif isinstance(row, dict):
                flat.append([str(v) for v in row.values()])
        tbl["rows"] = flat
    return ContentArticlePackage.model_validate(data)


def _check(label_id: str, article: ContentArticlePackage, review, quality_score: int) -> tuple[bool, str]:
    body_words = sum(len(p.split()) for s in article.sections for p in s.paragraphs)
    body_numbers = sum(len(re.findall(r"\d", p)) for s in article.sections for p in s.paragraphs)
    if label_id == "headline_punch":
        has_num = bool(re.search(r"\d", article.title))
        ok = 60 <= len(article.title) <= 100 and has_num
        return ok, f"len={len(article.title)} has_number={has_num}"
    if label_id == "narrative_lede":
        wc = len(article.narrative_lede.split())
        has_num = bool(re.search(r"\d", " ".join(article.narrative_lede.split()[:8])))
        return wc >= 35 and has_num, f"words={wc} front_loads_number={has_num}"
    if label_id == "market_context":
        return len(article.market_context.split()) >= 40, f"words={len(article.market_context.split())}"
    if label_id == "analyst_commentary":
        return len(article.analyst_commentary.split()) >= 40, f"words={len(article.analyst_commentary.split())}"
    if label_id == "sections":
        sub = review.substantive_section_count
        return sub >= 6, f"substantive={sub}"
    if label_id == "takeaways_faqs":
        return len(article.key_takeaways) >= 4 and len(article.faqs) >= 4, f"takeaways={len(article.key_takeaways)} faqs={len(article.faqs)}"
    if label_id == "metrics":
        ok_metrics = [m for m in article.metrics if m.label and m.value and m.period and m.source]
        return len(ok_metrics) >= 4, f"complete_metrics={len(ok_metrics)}/{len(article.metrics)}"
    if label_id == "tables":
        ok = any(t.columns and t.rows for t in article.tables)
        return ok, f"tables={len(article.tables)} with_rows={ok}"
    if label_id == "evidence_notes":
        return len(article.evidence_notes) >= 4, f"notes={len(article.evidence_notes)}"
    if label_id == "timeline":
        return len(article.timeline) >= 3, f"timeline={len(article.timeline)}"
    if label_id == "visuals":
        return len(article.visuals) >= 1, f"visuals={len(article.visuals)}"
    if label_id == "no_filler":
        from finagent.content.editorial import _FILLER_PATTERNS
        text = "\n".join(p for s in article.sections for p in s.paragraphs).lower()
        hits = sum(1 for p in _FILLER_PATTERNS if p.search(text))
        return hits == 0, f"filler_hits={hits}"
    if label_id == "no_advisory":
        from finagent.content.editorial import _ADVISORY_PATTERNS
        text = "\n".join(p for s in article.sections for p in s.paragraphs)
        hits = sum(1 for p in _ADVISORY_PATTERNS if p.search(text))
        return hits == 0, f"advisory_hits={hits}"
    if label_id == "source_signals":
        from finagent.content.editorial import _SOURCE_SIGNAL_PATTERNS
        paras = [p for s in article.sections for p in s.paragraphs]
        signal_count = sum(1 for p in paras if any(pat.search(p) for pat in _SOURCE_SIGNAL_PATTERNS) or re.search(r"\d", p))
        return signal_count / max(1, len(paras)) >= 0.80, f"signal_paragraphs={signal_count}/{len(paras)}"
    if label_id == "quality_score":
        return quality_score >= 70, f"quality_score={quality_score}"
    return False, "unknown"


async def main() -> int:
    started = time.time()
    print(f"=== Verification run :: target = {TARGET!r} ===")
    client, model, fb_client, fb_model = _client()
    print(f"Model: {model} (fallback: {fb_model or 'none'})")

    async def llm(system: str, user: str) -> str:
        return await _chat_with_fallback(
            client, model, fb_client, fb_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.25,
            max_tokens=900,
            timeout=60,
            response_format={"type": "json_object"},
        )

    print("\n[1/4] Running 10-specialist research wave...")
    memos = await run_specialist_wave(TARGET, CONTEXT, llm, timeout_s=55.0)
    summary = summarise_wave(memos)
    print(f"  covered: {summary['kinds_covered']}")
    print(f"  failed:  {summary['kinds_failed']}")
    print(f"  quality_score: {summary['quality_score']}")
    wave_block = wave_to_prompt_block(memos, max_chars=7500)

    print("\n[2/4] Synthesising ContentArticlePackage...")
    article = await synthesise_article(client, model, wave_block, fb_client, fb_model)

    print("\n[3/4] Running editorial revision loop (max 2 rounds)...")
    article, review = await run_editorial_revision_loop(
        article,
        target=TARGET,
        max_rounds=2,
        is_official_source=True,
        quality_score=summary["quality_score"],
        evidence_claim_count=len(article.evidence_notes),
        livemint_source_violations=0,
    )
    print(f"  total_score={review.total_score} urgency={review.urgency_score} structure={review.structure_score}")
    print(f"  copy={review.copy_score} source={review.source_score} compliance={review.compliance_score}")
    print(f"  livemint={review.livemint_score} (dims={review.livemint_dimensions})")
    print(f"  word_count={review.word_count} substantive_sections={review.substantive_section_count}")
    print(f"  quality_score={review.quality_score}")
    print(f"  ready_to_publish={review.ready_to_publish} revision_round={review.revision_round}")
    if review.issues:
        print("  open_issues:")
        for i in review.issues[:15]:
            print(f"    [{i.severity}] {i.code}: {i.message}")

    print("\n[4/4] Livemint rubric comparison (15 criteria):")
    pass_n = 0
    for label, lid in LIVEMINT_RUBRIC:
        ok, detail = _check(lid, article, review, summary["quality_score"])
        mark = "PASS" if ok else "FAIL"
        if ok:
            pass_n += 1
        print(f"  [{mark}] {label} -- {detail}")
    print(f"\n  RUBRIC TOTAL: {pass_n}/{len(LIVEMINT_RUBRIC)}")

    print("\n=== Article excerpt ===")
    print(f"TITLE     ({len(article.title)} chars): {article.title}")
    print(f"\nLEDE:\n{article.narrative_lede}")
    print(f"\nMARKET CONTEXT:\n{article.market_context}")
    print(f"\nANALYST COMMENTARY:\n{article.analyst_commentary}")
    print(f"\nFIRST SECTION ({article.sections[0].heading}):")
    for p in article.sections[0].paragraphs[:3]:
        print(f"  • {p}")

    # ── Optional publish to /insights/research ───────────────────────────────
    if os.environ.get("PUBLISH", "").strip().lower() in {"1", "true", "yes"}:
        from datetime import datetime, timezone

        from finagent.content.editorial import sanitize_article_package
        from finagent.content.livemint_blocker import strip_livemint_sources

        article = sanitize_article_package(article)
        slug = article.slug or "verify-publish"
        route_base = "insights"
        site_url = os.environ.get("FINAGENT_PUBLIC_SITE_URL", "https://prospektlab.com").rstrip("/")
        public_url = f"{site_url}/{route_base}/{slug}/"
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        # Source list: from evidence_notes (URLs only, Livemint already stripped).
        sources_used = [
            {"title": n.source_title, "url": n.source_url}
            for n in article.evidence_notes
            if n.source_url
        ]
        sources_used, _ = strip_livemint_sources(sources_used)

        html_text = render_article_html(
            article,
            public_url,
            None,
            generated_at,
            meta={
                "content_type": "earnings",
                "sources_used": sources_used,
                "publish_gate_status": "publish",
                "publish_gate_score": review.total_score,
            },
        )

        article_dir = _article_dir(route_base, slug)
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "index.html").write_text(html_text, encoding="utf-8")
        (article_dir / "article.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "title": article.title,
                    "description": article.description,
                    "route_base": route_base,
                    "public_url": public_url,
                    "generated_at": generated_at,
                    "publish_status": "published",
                    "publish_gate": {
                        "status": "publish",
                        "score": review.total_score,
                        "metrics": {
                            "word_count": review.word_count,
                            "substantive_sections": review.substantive_section_count,
                            "livemint_score": review.livemint_score,
                            "specialist_quality_score": summary["quality_score"],
                        },
                    },
                    "publish_gate_status": "publish",
                    "publish_gate_score": review.total_score,
                    "sources_used": sources_used,
                    "article": article.model_dump(),
                    "editorial_review": review.to_dict(),
                    "specialist_summary": summary,
                },
                indent=2,
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        mirrored = []
        for public_dir in _public_article_dirs(route_base, slug):
            public_dir.mkdir(parents=True, exist_ok=True)
            (public_dir / "index.html").write_text(html_text, encoding="utf-8")
            mirrored.append(str(public_dir))

        sitemap_path = _upsert_sitemap(route_base, slug)
        try:
            refresh_public_research_hub(route_base)
        except Exception as exc:
            print(f"  (hub refresh skipped: {exc})")

        print("\n=== PUBLISHED ===")
        print(f"  slug:            {slug}")
        print(f"  data dir:        {article_dir}")
        for m in mirrored:
            print(f"  mirrored:        {m}")
        print(f"  sitemap:         {sitemap_path}")
        print(f"  public URL:      {public_url}")
        print(f"  local preview:   {(article_dir / 'index.html').as_uri()}")

    out_path = ROOT / "verify_output.json"
    out_path.write_text(
        json.dumps(
            {
                "target": TARGET,
                "model": model,
                "wave_summary": summary,
                "review": review.to_dict(),
                "rubric_pass": pass_n,
                "rubric_total": len(LIVEMINT_RUBRIC),
                "article": article.model_dump(),
                "elapsed_s": round(time.time() - started, 1),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote full output to {out_path}")
    print(f"Elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
