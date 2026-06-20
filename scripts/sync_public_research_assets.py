from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from finagent.content_automation import (
    _article_dir,
    _public_article_dirs,
    list_generated_articles,
    load_generated_article_html,
    refresh_public_research_hub,
)


def _sync_article_assets(route_base: str, slug: str) -> None:
    source_dir = _article_dir(route_base, slug)
    html_text = load_generated_article_html(slug, route_base=route_base)
    if not html_text:
        return

    public_dirs = _public_article_dirs(route_base, slug)
    assets = [
        path for path in source_dir.iterdir()
        if path.is_file() and path.name not in {"article.json", "index.html"}
    ]

    for public_dir in public_dirs:
        public_dir.mkdir(parents=True, exist_ok=True)
        (public_dir / "index.html").write_text(html_text, encoding="utf-8")
        for asset in assets:
            shutil.copy2(asset, public_dir / asset.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resync public research pages from generated manifests.")
    parser.add_argument("--route-base", default="insights")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    items = list_generated_articles(route_base=args.route_base, limit=args.limit)
    published = [
        item for item in items
        if str(item.get("publish_status") or "").lower() == "published"
        and str(item.get("publish_gate_status") or "").lower() == "publish"
    ]
    for item in published:
        slug = str(item.get("slug") or "").strip()
        if slug:
            _sync_article_assets(args.route_base, slug)

    refresh_public_research_hub(args.route_base)
    print(f"synced {len(published)} published articles for route_base={args.route_base}")


if __name__ == "__main__":
    main()
