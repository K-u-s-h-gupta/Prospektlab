"""Tool registry (name → handler metadata)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolSpec:
    name: str
    description: str
    risk_level: int


RegistryMap = dict[str, ToolSpec]


def build_default_registry() -> RegistryMap:
    return {
        "web_search": ToolSpec("web_search", "Layered web search", 1),
        "web_fetch": ToolSpec("web_fetch", "Fetch URL body", 1),
        "browser_navigate": ToolSpec("browser_navigate", "Playwright navigation", 2),
        "deep_crawl_domain": ToolSpec("deep_crawl_domain", "DFS deep domain crawl via Playwright", 3),
        "file_read": ToolSpec("file_read", "Read local file", 2),
        "export_to_csv": ToolSpec("export_to_csv", "Export dataset (gated)", 4),
    }


def register_tool(registry: RegistryMap, spec: ToolSpec) -> None:
    registry[spec.name] = spec
