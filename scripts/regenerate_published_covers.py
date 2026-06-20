"""Regenerate cover images for all published research articles.

This script:
1. Loads every published article manifest under .finagent/content_automation/<route_base>.
2. Builds a story-matched editorial prompt per article.
3. Generates a fresh cover using Azure Foundry gpt-image-2 token auth.
4. Re-renders article HTML so the cover path is in sync.
5. Mirrors updated assets to frontend/public and frontend/app/public.

Usage:
  .venv-prospektlab311b\\Scripts\\python.exe scripts\\regenerate_published_covers.py
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

load_dotenv(ROOT / "backend" / "finagent" / ".env")

from finagent.content_automation import (  # noqa: E402
    ContentArticlePackage,
    _article_dir,
    _compose_editorial_cover_prompt,
    _public_article_dirs,
    list_generated_articles,
    load_generated_article,
    load_generated_article_html,
    refresh_public_research_hub,
)


def _sentiment_hint(article: ContentArticlePackage) -> str:
    text = " ".join(
        [
            article.title,
            article.description,
            article.hero_summary,
            article.narrative_lede,
            article.market_context,
            article.analyst_commentary,
        ]
    ).lower()
    positive_tokens = (
        "beat",
        "growth",
        "expansion",
        "record",
        "strong",
        "outperform",
        "upgrade",
        "improve",
        "higher",
        "surge",
    )
    negative_tokens = (
        "miss",
        "decline",
        "drop",
        "weak",
        "cut",
        "downgrade",
        "slump",
        "pressure",
        "fall",
        "risk",
        "shortfall",
    )
    pos = sum(token in text for token in positive_tokens)
    neg = sum(token in text for token in negative_tokens)
    if neg > pos:
        return "Sentiment is cautious and downside-aware; use restrained, serious visual cues."
    if pos > neg:
        return "Sentiment is constructive and momentum-focused; use confident but still professional visual cues."
    return "Sentiment is balanced and analytical; avoid overly celebratory or overly alarmist treatment."


def _article_payload_from_manifest(manifest: dict[str, Any], slug: str) -> dict[str, Any]:
    payload = manifest.get("article")
    if not isinstance(payload, dict):
        payload = {}
    payload = dict(payload)
    payload.setdefault("slug", manifest.get("slug") or slug)
    payload.setdefault("title", manifest.get("title") or slug.replace("-", " ").title())
    payload.setdefault(
        "description",
        manifest.get("description")
        or f"{payload['title']} update with company context, metrics, and implications.",
    )
    payload.setdefault("hero_title", payload.get("title") or manifest.get("title") or slug)
    payload.setdefault("hero_summary", payload.get("description") or manifest.get("description") or payload["title"])
    payload.setdefault("sections", [{"heading": "Overview", "paragraphs": [payload["description"]], "bullets": []}] * 4)
    payload.setdefault(
        "faqs",
        [
            {
                "question": "What changed in this story?",
                "answer": "The story has been updated with refreshed visual context and cover treatment.",
            },
            {
                "question": "Why does this update matter?",
                "answer": "It improves readability and better aligns visual context with the article narrative and tone.",
            },
            {
                "question": "What should readers watch next?",
                "answer": "Readers should track management commentary, forward guidance, and sector-level changes.",
            },
        ],
    )
    return payload


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_foundry_client(base_url: str) -> OpenAI:
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://ai.azure.com/.default",
    )
    return OpenAI(base_url=base_url, api_key=token_provider)


def _generate_image_bytes(client: OpenAI, deployment: str, prompt: str, size: str) -> bytes:
    response = client.images.generate(
        model=deployment,
        prompt=prompt,
        n=1,
        size=size,
    )
    data = response.data[0] if getattr(response, "data", None) else None
    if data is None:
        raise RuntimeError("Foundry returned no image payload")
    b64 = (
        getattr(data, "b64_json", None)
        or getattr(data, "image_base64", None)
        or getattr(data, "base64", None)
    )
    if not b64:
        raise RuntimeError("Foundry response did not include base64 image data")
    return base64.b64decode(b64)


def _with_proxy_cleared() -> dict[str, str | None]:
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    snapshot = {key: os.environ.get(key) for key in proxy_keys}
    for key in proxy_keys:
        os.environ.pop(key, None)
    return snapshot


def _restore_proxy(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def regenerate(
    route_base: str,
    *,
    limit: int | None = None,
    retries: int = 3,
    retry_delay_seconds: float = 2.5,
) -> tuple[int, int, list[str]]:
    items = list_generated_articles(route_base=route_base, limit=10_000)
    published = [
        item
        for item in items
        if str(item.get("publish_status") or "").lower() == "published"
        and str(item.get("publish_gate_status") or "publish").lower() in {"", "publish"}
    ]
    if limit:
        published = published[: max(1, limit)]

    base_url = (
        os.getenv("AZURE_GPT_IMAGE2_BASE_URL")
        or os.getenv("AZURE_AI_FOUNDRY_IMAGE_BASE_URL")
        or "https://prospektus-resource.services.ai.azure.com/openai/v1"
    ).rstrip("/")
    deployment = os.getenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT") or "gpt-image-2"
    size = os.getenv("FINAGENT_COVER_IMAGE_SIZE") or "1024x1024"

    azure_cfg = os.getenv("AZURE_CONFIG_DIR") or str(ROOT / ".azurecli")
    os.environ["AZURE_CONFIG_DIR"] = azure_cfg
    Path(azure_cfg).mkdir(parents=True, exist_ok=True)

    proxy_snapshot = _with_proxy_cleared()
    try:
        client = _build_foundry_client(base_url)
        ok = 0
        failed = 0
        errors: list[str] = []

        for item in published:
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            manifest = load_generated_article(slug, route_base=route_base)
            if not isinstance(manifest, dict):
                failed += 1
                errors.append(f"{slug}: manifest missing")
                continue

            try:
                article_payload = _article_payload_from_manifest(manifest, slug)
                article = ContentArticlePackage.model_validate(article_payload)
                sentiment = _sentiment_hint(article)
                prompt = _compose_editorial_cover_prompt(article)
                prompt = f"{prompt} {sentiment}"

                attempt = 0
                image_bytes: bytes | None = None
                last_error: Exception | None = None
                while attempt < max(1, retries):
                    attempt += 1
                    try:
                        image_bytes = _generate_image_bytes(client, deployment=deployment, prompt=prompt, size=size)
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < max(1, retries):
                            print(f"[retry] {slug}: attempt {attempt}/{retries} failed: {exc}")
                            time.sleep(max(0.0, retry_delay_seconds))
                if image_bytes is None:
                    raise RuntimeError(str(last_error) if last_error else "image generation failed")

                source_dir = _article_dir(route_base, slug)
                source_dir.mkdir(parents=True, exist_ok=True)
                cover_path = source_dir / "cover.png"
                _write_bytes(cover_path, image_bytes)

                manifest["image_path"] = str(cover_path)
                manifest["image_mime"] = "image/png"
                manifest["image_generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                manifest["cover_provider"] = "azure-foundry:gpt-image-2"
                if isinstance(manifest.get("article"), dict):
                    manifest["article"]["image_prompt"] = prompt[:1100]
                _write_text(source_dir / "article.json", json.dumps(manifest, indent=2, ensure_ascii=True))

                html_text = load_generated_article_html(slug, route_base=route_base)
                if html_text:
                    _write_text(source_dir / "index.html", html_text)

                public_dirs = _public_article_dirs(route_base, slug)
                assets = [
                    path
                    for path in source_dir.iterdir()
                    if path.is_file() and path.name != "article.json"
                ]
                for public_dir in public_dirs:
                    public_dir.mkdir(parents=True, exist_ok=True)
                    for asset in assets:
                        shutil.copy2(asset, public_dir / asset.name)

                ok += 1
                print(f"[ok] {slug}")
            except Exception as exc:
                failed += 1
                errors.append(f"{slug}: {exc}")
                print(f"[fail] {slug}: {exc}")

        refresh_public_research_hub(route_base)
        return ok, failed, errors
    finally:
        _restore_proxy(proxy_snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate Foundry cover images for all published articles.")
    parser.add_argument("--route-base", default="insights")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for quick runs.")
    parser.add_argument("--retries", type=int, default=3, help="Retry count per article for transient Foundry errors.")
    parser.add_argument("--retry-delay", type=float, default=2.5, help="Delay in seconds between per-article retries.")
    args = parser.parse_args()

    ok, failed, errors = regenerate(
        args.route_base,
        limit=(args.limit or None),
        retries=max(1, int(args.retries)),
        retry_delay_seconds=max(0.0, float(args.retry_delay)),
    )
    print(f"\nDone. regenerated={ok} failed={failed}")
    if errors:
        print("\nFailures:")
        for err in errors:
            print(f"- {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
