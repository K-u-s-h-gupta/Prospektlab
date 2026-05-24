"""
ORACLE FIOS - MCP Configuration
================================
Defines connection URLs for the FastMCP servers used by LangGraph.
"""

from __future__ import annotations

import os


def _mcp_url(env_name: str, default_port: int) -> str:
    return os.getenv(env_name, f"http://127.0.0.1:{default_port}/mcp")

# Connection settings for langchain-mcp-adapters MultiServerMCPClient
MCP_SERVERS = {
    "nse_india": {
        "url": _mcp_url("MCP_NSE_INDIA_URL", 8001),
        "transport": "streamable_http",
    },
    "fundamentals": {
        "url": _mcp_url("MCP_FUNDAMENTALS_URL", 8002),
        "transport": "streamable_http",
    },
    "research_news": {
        "url": _mcp_url("MCP_RESEARCH_URL", 8003),
        "transport": "streamable_http",
    },
    "docs_pipeline": {
        "url": _mcp_url("MCP_DOCS_URL", 8004),
        "transport": "streamable_http",
    },
    "valuation_engine": {
        "url": _mcp_url("MCP_VALUATION_URL", 8005),
        "transport": "streamable_http",
    },
    "forecasting": {
        "url": _mcp_url("MCP_FORECASTING_URL", 8006),
        "transport": "streamable_http",
    },
}
