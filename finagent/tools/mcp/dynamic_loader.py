"""Runtime MCP discovery (extend with your Cursor / stdio / HTTP mounts)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.mcp.dynamic_loader")


@dataclass
class MCPServerRef:
    name: str
    transport: str
    url_or_command: str


def discover_servers_from_env() -> list[MCPServerRef]:
    """Discover MCP endpoints from skills/*.json files or MCP_REGISTRY_PATH."""
    refs: list[MCPServerRef] = []
    registry_path = Path(__import__("os").environ.get("MCP_REGISTRY_PATH", "")) if __import__("os").environ.get("MCP_REGISTRY_PATH") else None
    candidates: list[Path] = []
    if registry_path and registry_path.exists():
        candidates.append(registry_path)
    skills_dir = Path.cwd() / "skills"
    if skills_dir.exists():
        candidates.extend(skills_dir.rglob("*.json"))

    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            for name, cfg in servers.items():
                if not isinstance(cfg, dict):
                    continue
                if cfg.get("url"):
                    refs.append(MCPServerRef(name=name, transport="http", url_or_command=str(cfg["url"])))
                elif cfg.get("command"):
                    refs.append(MCPServerRef(name=name, transport="stdio", url_or_command=str(cfg["command"])))
    if not refs:
        logger.warning("No MCP endpoints discovered from MCP_REGISTRY_PATH or skills/*.json")
    return refs
