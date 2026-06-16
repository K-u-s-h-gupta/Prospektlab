"""Minimal footprint: tool risk levels and permission scope."""

from __future__ import annotations

from dataclasses import dataclass

TOOL_RISK_LEVELS: dict[str, int] = {
    "web_search": 1,
    "web_fetch": 1,
    "browser_navigate": 2,
    "deep_crawl_domain": 3,
    "file_read": 2,
    "file_write": 3,
    "enrich_business": 3,
    "enrich_prospects": 3,
    "export_to_csv": 4,
    "crm_write": 5,
}

MAX_LEVEL_WITHOUT_GATE = 2


@dataclass
class PermissionScope:
    max_risk_level: int = MAX_LEVEL_WITHOUT_GATE


class FootprintEnforcer:
    def __init__(self, scope: PermissionScope) -> None:
        self.scope = scope

    def assert_allowed(self, tool_name: str) -> None:
        level = TOOL_RISK_LEVELS.get(tool_name, 2)
        if level > self.scope.max_risk_level:
            raise PermissionError(
                f"Tool {tool_name} (risk {level}) exceeds scope max {self.scope.max_risk_level}"
            )
