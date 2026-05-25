"""
ORACLE FIOS - MCP Configuration
================================
Defines connection URLs for the FastMCP servers used by LangGraph.
"""

from __future__ import annotations

import os


def _mcp_url(env_name: str, default_port: int) -> str:
    return os.getenv(env_name, f"http://127.0.0.1:{default_port}/mcp")

# Connection settings for langchain-mcp-adapters MultiServerMCPClient.
# ProspektLab v3 exposes exactly two execution servers.
MCP_SERVERS = {
    "discovery": {
        "url": _mcp_url("MCP_DISCOVERY_URL", 8003),
        "transport": "streamable_http",
    },
    "quant": {
        "url": _mcp_url("MCP_QUANT_URL", 8005),
        "transport": "streamable_http",
    },
}
