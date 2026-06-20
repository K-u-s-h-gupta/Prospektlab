"""Delete every previously-published article from the three insights mirrors
and strip their entries from the sitemaps. Static hub pages (research,
strategy, organic-traffic-platform, etc.) are preserved by detecting the
`article.json` marker.

Usage:
  .venv-prospektlab311b\\Scripts\\python.exe scripts\\cleanup_published.py [--dry-run]
"""

from __future__ import annotations

import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSIGHTS_DIRS = [
    ROOT / ".finagent" / "content_automation" / "insights",
    ROOT / "frontend" / "public" / "insights",
    ROOT / "frontend" / "app" / "public" / "insights",
]
SITEMAPS = [
    ROOT / "frontend" / "app" / "public" / "sitemap.xml",
    ROOT / "frontend" / "public" / "sitemap.xml",
    ROOT / "frontend" / "dist" / "sitemap.xml",
]
DRY = "--dry-run" in sys.argv


def is_article_dir(d: Path) -> bool:
    if not d.is_dir():
        return False
    if (d / "article.json").is_file():
        return True
    # Mirror dirs may have only index.html — detect via slug shape (heuristic:
    # the dir name contains hyphens AND no obvious static-page name).
    static_names = {"research", "strategy", "organic-traffic-platform", "studio", "tools"}
    if d.name in static_names:
        return False
    if (d / "index.html").is_file() and "-" in d.name:
        return True
    return False


def gather_slugs() -> set[str]:
    slugs: set[str] = set()
    for base in INSIGHTS_DIRS:
        if not base.exists():
            continue
        for child in base.iterdir():
            if is_article_dir(child):
                slugs.add(child.name)
    return slugs


def delete_article_dirs(slugs: set[str]) -> int:
    n = 0
    for base in INSIGHTS_DIRS:
        for slug in slugs:
            d = base / slug
            if d.exists() and d.is_dir():
                if DRY:
                    print(f"  [dry] would remove {d}")
                else:
                    shutil.rmtree(d, ignore_errors=True)
                n += 1
    return n


def strip_sitemap_entries(slugs: set[str]) -> None:
    for sm in SITEMAPS:
        if not sm.is_file():
            continue
        try:
            text = sm.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
            ET.register_namespace("", ns)
            root = ET.fromstring(text)
        except ET.ParseError:
            print(f"  [warn] could not parse {sm} — skipped")
            continue
        removed = 0
        for url_el in list(root.findall(f"{{{ns}}}url")):
            loc_el = url_el.find(f"{{{ns}}}loc")
            if loc_el is None or not loc_el.text:
                continue
            loc = loc_el.text.strip()
            if any(f"/insights/{slug}" in loc for slug in slugs):
                root.remove(url_el)
                removed += 1
        if removed:
            if DRY:
                print(f"  [dry] would strip {removed} entries from {sm}")
            else:
                ET.ElementTree(root).write(sm, encoding="utf-8", xml_declaration=True)
                print(f"  Stripped {removed} entries from {sm}")


def main() -> int:
    slugs = gather_slugs()
    print(f"Found {len(slugs)} published articles to remove:")
    for slug in sorted(slugs):
        print(f"  - {slug}")
    if not slugs:
        return 0
    removed = delete_article_dirs(slugs)
    print(f"\nDirectories removed (across mirrors): {removed}")
    strip_sitemap_entries(slugs)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
