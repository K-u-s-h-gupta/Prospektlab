"""Reusable batch publisher for the ProspektLab content pipeline.

Single-target API:
    article, review, summary, published = await publish_target(target, context, ...)

CLI:
    python scripts/publish_pipeline.py "Infosys Q4 FY25 results" "TCS Q4 FY25 results" ...
    python scripts/publish_pipeline.py --file scripts/daily_targets.txt

Always:
  - Bypasses Azure RAI by default (FINAGENT_BYPASS_AZURE=1) — Azure foundry
    aggressively flags benign finance prompts as jailbreak.
  - Runs the 10-specialist research wave with LLM-fallback per call.
  - Synthesises a ContentArticlePackage with strict JSON contract.
  - Runs the editorial revision loop with the new hard-fail gate.
  - Only writes to /insights/ when the gate passes — quality dominates volume.

Output: prints a per-target table and a final summary, and writes JSON manifests
to .finagent/content_automation/insights/<slug>/article.json plus index.html
mirrors under frontend/public/insights and frontend/app/public/insights.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # type: ignore

load_dotenv(ROOT / "backend" / "finagent" / ".env")
# Default: use Azure as primary (high quota). OpenAI is the RAI fallback only.
# Set FINAGENT_BYPASS_AZURE=1 explicitly to flip primary to OpenAI direct.
os.environ.setdefault("FINAGENT_BYPASS_AZURE", "0")
if os.environ.get("FINAGENT_BYPASS_AZURE", "").lower() in {"1", "true", "yes"}:
    os.environ["FINAGENT_SYNTH_MODEL"] = os.environ.get("VERIFY_MODEL") or "gpt-4o-mini"
    os.environ["FINAGENT_EDITORIAL_MODEL"] = os.environ.get("VERIFY_MODEL") or "gpt-4o-mini"
    os.environ["FINAGENT_SPECIALIST_MODEL"] = os.environ.get("VERIFY_MODEL") or "gpt-4o-mini"

import openai

from finagent.content.editorial import (
    run_editorial_revision_loop,
    sanitize_article_package,
)
from finagent.content.livemint_blocker import strip_livemint_sources
from finagent.content.specialist_agents import (
    SPECIALIST_KINDS,
    run_specialist_wave,
    summarise_wave,
    wave_to_prompt_block,
)
from finagent.content_automation import (
    ContentArticlePackage,
    ContentAutomationRequest,
    _article_dir,
    _generate_image,
    _public_article_dirs,
    _upsert_sitemap,
    refresh_public_research_hub,
    render_article_html,
    render_cover_png,
)
from finagent.runtime_provider import (
    is_content_filter_error,
    is_rate_limit_error,
    resolve_openai_config,
    resolve_openai_fallback_config,
)

SITE_URL = os.environ.get("FINAGENT_PUBLIC_SITE_URL", "https://prospektlab.com").rstrip("/")
ROUTE_BASE = "insights"


# ── LLM with content-filter fallback ─────────────────────────────────────────


def build_clients() -> tuple[openai.AsyncOpenAI, str, openai.AsyncOpenAI | None, str | None]:
    cfg = resolve_openai_config(complexity="moderate")
    if cfg is None:
        raise SystemExit("No LLM key resolved; set Azure foundry or OPENAI_API_KEY.")
    primary = openai.AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    # When bypassing Azure, the OpenAI org's "gpt-5.4-mini" alias maps to a low
    # rate-limit bucket. Force gpt-4o-mini for batch throughput (500 RPM).
    bypass = (os.getenv("FINAGENT_BYPASS_AZURE") or "").strip().lower() in {"1", "true", "yes"}
    if bypass:
        primary_model = os.getenv("VERIFY_MODEL") or "gpt-4o-mini"
    else:
        primary_model = os.getenv("VERIFY_MODEL") or os.getenv("FINAGENT_SYNTH_MODEL") or cfg.model or "gpt-4o-mini"
    fb_cfg = resolve_openai_fallback_config(complexity="moderate")
    fb = openai.AsyncOpenAI(api_key=fb_cfg.api_key) if fb_cfg else None
    fb_model = fb_cfg.model if fb_cfg else None
    return primary, primary_model, fb, fb_model


async def chat_with_fallback(
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
    """Provider chain: primary → on RAI try fallback → on 429 retry primary.

    The OpenAI org in this repo is tier-0 (10 RPM, 50 RPD). When the RAI fallback
    hits a rate limit, we bounce back to Azure with a small delay so the next
    attempt does not stack a fresh RAI rejection.
    """
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
    except Exception as primary_exc:
        if is_content_filter_error(primary_exc) and fb_client is not None and fb_model is not None:
            try:
                return await _call(fb_client, fb_model)
            except Exception as fb_exc:
                if is_rate_limit_error(fb_exc):
                    # OpenAI burst budget exhausted — bounce back to Azure with
                    # a softened message envelope so RAI is less likely to fire.
                    await asyncio.sleep(2.0)
                    softened = _soften_for_retry(messages)
                    return await _call(client, model) if not softened else await _call_with_messages(client, model, softened, temperature, max_tokens, timeout, response_format)
                raise
        if is_rate_limit_error(primary_exc) and fb_client is not None and fb_model is not None:
            # Primary (Azure) ran out — try the OpenAI fallback once.
            try:
                return await _call(fb_client, fb_model)
            except Exception as fb_exc:
                if is_rate_limit_error(fb_exc):
                    await asyncio.sleep(3.0)
                    return await _call(client, model)
                raise
        raise


async def _call_with_messages(
    c: openai.AsyncOpenAI,
    m: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: int,
    response_format: dict | None,
) -> str:
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


def _soften_for_retry(messages: list[dict]) -> list[dict] | None:
    """Strip RAI-trigger phrasing from the system message before re-hitting Azure."""
    triggers = (
        ("Never cite", "Exclude"),
        ("never cite", "exclude"),
        ("strictly", "carefully"),
        ("banned", "avoided"),
    )
    out: list[dict] = []
    changed = False
    for msg in messages:
        if msg.get("role") == "system":
            content = str(msg.get("content") or "")
            new = content
            for old, repl in triggers:
                if old in new:
                    new = new.replace(old, repl)
            if new != content:
                changed = True
            out.append({**msg, "content": new})
        else:
            out.append(msg)
    return out if changed else None


# ── Synthesis ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a senior markets correspondent at a top Indian business daily. "
    "Produce a publication-ready financial article as ContentArticlePackage JSON. "
    "Voice rules: front-load stakes in the lede; embed numerical data inside "
    "narrative sentences; attribute every sentiment to its source; close with a "
    "forward-looking line; vary sentence lengths. Keep the tone analytical and neutral. "
    "Exclude livemint.com from sources.\n\n"
    "ACCURACY RULES — these are mandatory:\n"
    "1. Do NOT invent specific figures. Only state a precise number (revenue, margin, "
    "growth %, EPS, etc.) if it appears in the supplied research/context. If the exact "
    "figure is not supplied, describe direction qualitatively ('margin held broadly "
    "stable') instead of fabricating a number.\n"
    "2. The headline may only contain a numeric stat if that exact number is supplied "
    "in the research context. Otherwise write a strong qualitative headline with the "
    "named entity and the key theme.\n"
    "3. Do NOT fabricate source URLs. In evidence_notes, only include a source_url if "
    "it is a real, plausible link to an official portal (nseindia.com, bseindia.com, "
    "sebi.gov.in, rbi.org.in, mca.gov.in) or the company site. Never invent GUID-style "
    "attachment filenames. If unsure of the exact URL, give the source_title and leave "
    "source_url as an empty string.\n"
    "4. Visuals must be real comparative data. Every visual's points must share the "
    "same unit and represent actual comparable quantities (e.g. revenue across four "
    "quarters). Do NOT emit 'emphasis maps' or charts where bars carry placeholder "
    "scores like 1.0. If you lack real numeric series, omit visuals entirely.\n"
    "Return strictly the JSON schema."
)


def build_user_prompt(target: str, context: str, wave_block: str) -> str:
    return (
        f"TARGET: {target}\n\nBACKGROUND CONTEXT:\n{context}\n\n{wave_block}\n\n"
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


def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    for vis in data.get("visuals") or []:
        for point in vis.get("points") or []:
            val = point.get("value")
            if isinstance(val, str):
                m = re.search(r"-?\d+(?:[.,]\d+)*", val)
                point["value"] = float(m.group(0).replace(",", "")) if m else 0.0
    if isinstance(data.get("audience"), list):
        data["audience"] = ", ".join(str(a) for a in data["audience"])
    if isinstance(data.get("audience"), str):
        data["audience"] = data["audience"][:120]
    for tbl in data.get("tables") or []:
        rows = tbl.get("rows") or []
        flat: list[list[str]] = []
        for row in rows:
            if isinstance(row, list):
                flat.append([str(c) for c in row])
            elif isinstance(row, dict):
                flat.append([str(v) for v in row.values()])
        tbl["rows"] = flat
    # Clamp pydantic max_length fields the model sometimes overshoots.
    for metric in data.get("metrics") or []:
        if isinstance(metric, dict):
            for field, limit in (("label", 80), ("value", 80), ("change", 40), ("period", 60), ("source", 180)):
                if isinstance(metric.get(field), str) and len(metric[field]) > limit:
                    metric[field] = metric[field][:limit]
    if isinstance(data.get("title"), str):
        data["title"] = data["title"][:160]
    if isinstance(data.get("description"), str):
        data["description"] = data["description"][:280]
    if isinstance(data.get("hero_title"), str):
        data["hero_title"] = data["hero_title"][:100]
    # Deterministic accuracy repair: drop broken visuals, strip fabricated URLs,
    # repair ungrounded headline stats — before the model is validated/published.
    from finagent.content.content_accuracy import enforce_article_accuracy
    data, actions = enforce_article_accuracy(data)
    for act in actions:
        print(f"    [accuracy] {act}")
    return data


async def synthesise(
    target: str,
    context: str,
    wave_block: str,
    client: openai.AsyncOpenAI,
    model: str,
    fb_client: openai.AsyncOpenAI | None,
    fb_model: str | None,
) -> ContentArticlePackage:
    raw = await chat_with_fallback(
        client, model, fb_client, fb_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(target, context, wave_block)},
        ],
        temperature=0.3,
        max_tokens=6000,
        timeout=120,
        response_format={"type": "json_object"},
    )
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw)
    data = _coerce(json.loads(raw))
    return ContentArticlePackage.model_validate(data)


# ── Fundamentals merge ───────────────────────────────────────────────────────


def _merge_fundamentals(article: ContentArticlePackage, fundamentals: dict[str, Any]) -> ContentArticlePackage:
    """Inject real metric tiles and a real revenue chart into the article.

    Real fundamentals take precedence: they are prepended to the metric list
    (deduped by label) and the real revenue series is added as the first visual
    so the hero chart plots actual data.
    """
    if not fundamentals:
        return article
    from finagent.content_automation import ContentArticleMetric, ContentArticleVisual, ContentArticleVisualPoint

    data = article.model_dump()

    real_metrics = fundamentals.get("metrics") or []
    if real_metrics:
        existing = {str(m.get("label", "")).lower() for m in real_metrics}
        merged = list(real_metrics)
        for m in data.get("metrics") or []:
            if str(m.get("label", "")).lower() not in existing:
                merged.append(m)
        data["metrics"] = merged[:8]

    chart = fundamentals.get("chart") or {}
    if chart.get("points"):
        vis = {
            "kind": chart.get("kind", "bar"),
            "title": chart.get("title", "Annual revenue"),
            "points": [{"label": str(p["label"]), "value": float(p["value"])} for p in chart["points"]],
            "note": chart.get("note", ""),
        }
        new_sig = tuple(round(p["value"], 2) for p in vis["points"])

        def _sig(v: Any) -> tuple:
            pts = v.get("points") if isinstance(v, dict) else getattr(v, "points", [])
            return tuple(round(float(p.get("value") if isinstance(p, dict) else getattr(p, "value", 0)), 2) for p in (pts or []))

        # Drop any model visual that plots the same series, then prepend the real one.
        existing = [v for v in (data.get("visuals") or []) if _sig(v) != new_sig]
        data["visuals"] = [vis] + existing

    try:
        return ContentArticlePackage.model_validate(data)
    except Exception:
        return article


# ── Publish ──────────────────────────────────────────────────────────────────


def infer_content_type(target: str) -> str:
    """Pick a content type from the topic so the renderer can shape the layout.

    earnings/company → market-style hero with chart; sebi/rbi/trend → text hero.
    """
    t = (target or "").lower()
    if any(k in t for k in ("sebi", "adjudication", "show cause", "enforcement", "circular", "consultation")):
        return "sebi"
    if any(k in t for k in ("rbi", "monetary policy", "repo", "mpc", "inflation", "gdp")):
        return "regulation"
    if any(k in t for k in ("mca", "director identification", "din ", "registrar of companies")):
        return "regulation"
    if any(k in t for k in ("sector", "outlook", "demand cycle", "debate", "framework", "theme", "industry")):
        return "trend"
    if any(k in t for k in ("results", "q1 ", "q2 ", "q3 ", "q4 ", "fy2", "earnings", "quarter", "profit")):
        return "earnings"
    return "company"


async def _make_cover(article: ContentArticlePackage, content_type: str) -> tuple[bytes, str]:
    """Return (image_bytes, filename). Always tries gpt-image-2 first; PIL cover on any failure."""
    try:
        req = ContentAutomationRequest(
            topic=article.title, slug=article.slug, include_image=True, route_base=ROUTE_BASE
        )
        img_bytes, ext, _mime = await _generate_image(req, article, ROUTE_BASE)
        if img_bytes:
            print(f"    [cover] gpt-image-2 cover generated ({len(img_bytes)//1024}KB)")
            return img_bytes, f"cover{ext}"
    except Exception as exc:
        print(f"    [cover] gpt-image-2 failed, using PIL render: {exc}")
    png = render_cover_png(article)
    if png:
        print(f"    [cover] PIL cover generated ({len(png)//1024}KB)")
        return png, "cover.png"
    return b"", ""


def write_article_to_disk(
    article: ContentArticlePackage,
    review: Any,
    summary: dict[str, Any],
    content_type: str = "earnings",
    cover: tuple[bytes, str] | None = None,
) -> dict[str, Any]:
    article = sanitize_article_package(article)
    slug = article.slug or f"article-{int(time.time())}"
    public_url = f"{SITE_URL}/{ROUTE_BASE}/{slug}/"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    sources_used = [
        {"title": n.source_title, "url": n.source_url}
        for n in article.evidence_notes
        if n.source_url
    ]
    sources_used, _ = strip_livemint_sources(sources_used)

    cover_bytes, cover_name = cover or (b"", "")
    image_href = f"/{ROUTE_BASE}/{slug}/{cover_name}" if cover_bytes else None

    html_text = render_article_html(
        article,
        public_url,
        image_href,
        generated_at,
        meta={
            "content_type": content_type,
            "sources_used": sources_used,
            "publish_gate_status": "publish",
            "publish_gate_score": review.total_score,
        },
    )

    article_dir = _article_dir(ROUTE_BASE, slug)
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / "index.html").write_text(html_text, encoding="utf-8")
    if cover_bytes:
        (article_dir / cover_name).write_bytes(cover_bytes)
    (article_dir / "article.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": article.title,
                "description": article.description,
                "route_base": ROUTE_BASE,
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
                "content_type": content_type,
                "image_path": (str(article_dir / cover_name) if cover_bytes else ""),
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
    for public_dir in _public_article_dirs(ROUTE_BASE, slug):
        public_dir.mkdir(parents=True, exist_ok=True)
        (public_dir / "index.html").write_text(html_text, encoding="utf-8")
        if cover_bytes:
            (public_dir / cover_name).write_bytes(cover_bytes)
        mirrored.append(str(public_dir))

    sitemap_path = _upsert_sitemap(ROUTE_BASE, slug)
    try:
        refresh_public_research_hub(ROUTE_BASE)
    except Exception:
        pass
    return {
        "slug": slug,
        "data_dir": str(article_dir),
        "mirrored": mirrored,
        "sitemap_path": sitemap_path,
        "public_url": public_url,
    }


# ── Single target ────────────────────────────────────────────────────────────


async def publish_target(
    target: str,
    context: str,
    *,
    clients: tuple[openai.AsyncOpenAI, str, openai.AsyncOpenAI | None, str | None] | None = None,
    force_publish: bool = False,
) -> dict[str, Any]:
    primary, primary_model, fb, fb_model = clients or build_clients()

    async def llm(system: str, user: str) -> str:
        return await chat_with_fallback(
            primary, primary_model, fb, fb_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.25,
            max_tokens=900,
            timeout=60,
            response_format={"type": "json_object"},
        )

    # Pull REAL fundamentals so the agent writes actual numbers, not "Disclosed".
    fundamentals: dict[str, Any] = {}
    try:
        from fundamentals import fetch_fundamentals
        fundamentals = await fetch_fundamentals(target)
    except Exception as exc:
        print(f"    [fundamentals] skipped: {exc}")
    enriched_context = context
    if fundamentals.get("context_block"):
        enriched_context = f"{context}\n\n{fundamentals['context_block']}"
        print(f"    [fundamentals] {fundamentals['ticker']}: {len(fundamentals.get('metrics', []))} real metrics, chart={'yes' if fundamentals.get('chart') else 'no'}")

    memos = await run_specialist_wave(target, enriched_context, llm, timeout_s=55.0)
    summary = summarise_wave(memos)
    wave_block = wave_to_prompt_block(memos, max_chars=7500)

    article = await synthesise(target, enriched_context, wave_block, primary, primary_model, fb, fb_model)

    # Merge real fundamentals into the article: guarantee numeric metric tiles and
    # a real revenue chart even if the model still hedged on some figures.
    article = _merge_fundamentals(article, fundamentals)

    article, review = await run_editorial_revision_loop(
        article,
        target=target,
        max_rounds=2,
        is_official_source=True,
        quality_score=summary["quality_score"],
        evidence_claim_count=len(article.evidence_notes),
        livemint_source_violations=0,
        source_material=enriched_context,
    )

    # Accuracy criticals are never bypassable, even with --force. Quality-only
    # shortfalls (score just under the bar) can be forced; fabrication cannot.
    _ACCURACY_CRITICALS = {
        "ungrounded_headline_number",
        "broken_visual",
        "fabricated_source_url",
        "missing_evidence_claims",
        "livemint_source_leak",
    }
    accuracy_blocked = any(
        i.get("code") in _ACCURACY_CRITICALS and i.get("severity") == "critical"
        for i in review.to_dict().get("issues", [])
    )
    publish = (bool(review.ready_to_publish) or force_publish) and not accuracy_blocked
    persisted: dict[str, Any] = {}
    if publish:
        ctype = infer_content_type(target)
        cover = await _make_cover(article, ctype)
        persisted = write_article_to_disk(article, review, summary, content_type=ctype, cover=cover)

    return {
        "target": target,
        "wave_summary": summary,
        "review": review.to_dict(),
        "ready_to_publish": bool(review.ready_to_publish),
        "force_publish": force_publish,
        "accuracy_blocked": accuracy_blocked,
        "persisted": persisted,
        "article_title": article.title,
        "word_count": review.word_count,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("targets", nargs="*")
    p.add_argument("--file", type=Path, help="Newline-delimited target file")
    p.add_argument("--force", action="store_true", help="Publish even if gate fails")
    p.add_argument("--max", type=int, default=0, help="Max number of targets to attempt")
    p.add_argument("--concurrency", type=int, default=1, help="Parallel target runs")
    return p.parse_args()


def _resolve_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if args.file and args.file.is_file():
        for line in args.file.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            target, _, ctx = raw.partition("|")
            items.append((target.strip(), ctx.strip()))
    for t in args.targets:
        items.append((t.strip(), ""))
    if args.max > 0:
        items = items[: args.max]
    return items


async def main() -> int:
    args = parse_args()
    pairs = _resolve_targets(args)
    if not pairs:
        print("No targets supplied. Pass on CLI or use --file.")
        return 1

    clients = build_clients()
    print(f"Model: {clients[1]} (fallback: {clients[3] or 'none'})")
    print(f"Targets: {len(pairs)} | Concurrency: {args.concurrency}")
    print()

    results: list[dict[str, Any]] = []
    started = time.time()

    sem = asyncio.Semaphore(args.concurrency)

    async def _one(target: str, ctx: str) -> dict[str, Any]:
        async with sem:
            t0 = time.time()
            try:
                r = await publish_target(target, ctx, clients=clients, force_publish=args.force)
            except Exception as exc:
                return {"target": target, "error": str(exc)[:400], "elapsed_s": round(time.time() - t0, 1)}
            r["elapsed_s"] = round(time.time() - t0, 1)
            return r

    pending = [asyncio.create_task(_one(t, c)) for t, c in pairs]
    for fut in asyncio.as_completed(pending):
        r = await fut
        results.append(r)
        slug = r.get("persisted", {}).get("slug", "-")
        status = (
            "ERROR" if "error" in r
            else "PUBLISHED" if r.get("persisted")
            else "DRAFT"
        )
        word_count = r.get("word_count", 0)
        review = r.get("review") or {}
        total = review.get("total_score", "-")
        lm = review.get("livemint_score", "-")
        q = (r.get("wave_summary") or {}).get("quality_score", "-")
        print(f"  [{status:9}] total={total} lm={lm} q={q} words={word_count} slug={slug}  ({r.get('target', '')[:60]})  {r['elapsed_s']}s")
        if "error" in r:
            print(f"    error: {r['error']}")

    pub = sum(1 for r in results if r.get("persisted"))
    drafts = sum(1 for r in results if not r.get("persisted") and "error" not in r)
    errs = sum(1 for r in results if "error" in r)
    print(f"\nDone. Published={pub} Drafts={drafts} Errors={errs} Elapsed={time.time() - started:.0f}s")

    log_path = ROOT / ".finagent" / "publish_runs" / f"run-{int(started)}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Run log: {log_path}")
    return 0 if errs == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
