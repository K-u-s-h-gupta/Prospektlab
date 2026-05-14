"""Runtime MCP discovery (extend with your Cursor / stdio / HTTP mounts)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MCPServerRef:
    name: str
    transport: str
    url_or_command: str


def discover_servers_from_env() -> list[MCPServerRef]:
    """Placeholder: read JSON config path from MCP_REGISTRY_PATH."""
    return []
