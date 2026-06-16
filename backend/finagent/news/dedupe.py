"""News deduplication module.

Canonicalizes URLs, fingerprints titles, merges duplicates.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


def canonicalize_url(url: str) -> str:
    """Strip query/fragment/UTM, lowercase host, return canonical URL."""
    url = url.strip().lower()
    # Remove protocol
    url = re.sub(r"^https?://", "", url)
    # Remove www.
    url = re.sub(r"^www\.", "", url)
    # Remove query string and fragment
    url = url.split("?")[0].split("#")[0]
    # Remove trailing slash
    url = url.rstrip("/")
    return url


def title_fingerprint(title: str) -> str:
    """First 6 significant words → hash."""
    words = re.findall(r"[a-zA-Z0-9]+", title.lower())
    # Filter out very short words (common stop words)
    significant = [w for w in words if len(w) > 2][:6]
    return hashlib.sha256(" ".join(significant).encode()).hexdigest()[:16]


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate news items by URL or title fingerprint.
    Keep highest source tier on merge.
    """
    seen: dict[str, dict[str, Any]] = {}  # key -> best item

    for item in items:
        url = item.get("url", "")
        title = item.get("title", "")
        canon_url = canonicalize_url(url) if url else ""
        fp = title_fingerprint(title) if title else ""

        key = canon_url if canon_url else (fp if fp else f"anon:{id(item)}")

        if key not in seen:
            seen[key] = item
        else:
            existing = seen[key]
            # Prefer verified (lower tier number = higher trust)
            existing_tier = existing.get("source_tier", 3)
            new_tier = item.get("source_tier", 3)
            if new_tier < existing_tier:
                seen[key] = item
            # Merge snippets if new one is longer
            elif len(item.get("snippet", "")) > len(existing.get("snippet", "")):
                seen[key] = item

    # Return in original order (by first occurrence of each unique key)
    result = []
    used_keys: set[str] = set()
    for item in items:
        url = item.get("url", "")
        title = item.get("title", "")
        canon_url = canonicalize_url(url) if url else ""
        fp = title_fingerprint(title) if title else ""
        key = canon_url if canon_url else (fp if fp else f"anon:{id(item)}")
        if key not in used_keys:
            used_keys.add(key)
            result.append(seen[key])

    return result
