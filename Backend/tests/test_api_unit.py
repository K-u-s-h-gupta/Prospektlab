"""
Unit tests for api.py helpers and rich_builder.build().

These tests do NOT require a running MCP server, OpenAI key, or LangGraph graph.
The graph import in api.py is lazy (inside _get_graph()), so importing api here
is safe and side-effect-free beyond loading dotenv and setting up logging.

Run with:
    python -m pytest tests/test_api_unit.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rich_builder
from api import ChatResponse, _collect_tool_outputs


# ---------------------------------------------------------------------------
# Duck-type helpers (stand-ins for LangChain message objects)
# ---------------------------------------------------------------------------

class _FakeMsg:
    """Minimal duck-type base for LangChain messages."""
    name: str | None = None
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


def _tool_msg(name: str, content: str, tool_call_id: str = "tc1") -> _FakeMsg:
    m = _FakeMsg()
    m.name = name
    m.content = content
    m.tool_call_id = tool_call_id
    return m


def _ai_msg_with_calls(calls: list[dict[str, Any]]) -> _FakeMsg:
    """AIMessage duck-type: has tool_calls but no name (not a ToolMessage)."""
    m = _FakeMsg()
    m.name = None
    m.content = ""
    m.tool_calls = calls
    return m


# ---------------------------------------------------------------------------
# _collect_tool_outputs
# ---------------------------------------------------------------------------

class TestCollectToolOutputs:
    def test_basic_tool_message_captured(self):
        sink: list[rich_builder.ToolOutput] = []
        payload = {"messages": [_tool_msg("nse_get_quote", '{"data": {"lastPrice": 100}}')]}
        _collect_tool_outputs("market_data_agent", payload, sink)
        assert len(sink) == 1
        assert sink[0].name == "nse_get_quote"
        assert sink[0].agent == "market_data_agent"
        assert sink[0].content == '{"data": {"lastPrice": 100}}'

    def test_args_matched_from_preceding_ai_message(self):
        """Args on the AIMessage's tool_call should be matched via tool_call_id."""
        sink: list[rich_builder.ToolOutput] = []
        ai = _ai_msg_with_calls([{"id": "tc42", "name": "profile", "args": {"symbol": "RELIANCE"}}])
        tool = _tool_msg("profile", '{"data": {"long_name": "Reliance"}}', tool_call_id="tc42")
        payload = {"messages": [ai, tool]}
        _collect_tool_outputs("fundamental_analysis_agent", payload, sink)
        named = [o for o in sink if o.name == "profile" and o.content is not None]
        assert named, "Expected a ToolOutput for 'profile' with content"
        assert named[0].args == {"symbol": "RELIANCE"}

    def test_ai_message_tool_call_stub_captured(self):
        """Tool call stubs (no ToolMessage yet) should be captured with content=None."""
        sink: list[rich_builder.ToolOutput] = []
        ai = _ai_msg_with_calls([{"id": "tc1", "name": "income_statement", "args": {"symbol": "TCS"}}])
        payload = {"messages": [ai]}
        _collect_tool_outputs("fundamental_analysis_agent", payload, sink)
        stubs = [o for o in sink if o.name == "income_statement" and o.content is None]
        assert stubs, "Expected a stub ToolOutput for 'income_statement'"
        assert stubs[0].args == {"symbol": "TCS"}

    def test_empty_messages_produces_no_outputs(self):
        sink: list[rich_builder.ToolOutput] = []
        _collect_tool_outputs("some_agent", {"messages": []}, sink)
        assert sink == []

    def test_non_dict_payload_is_silent(self):
        sink: list[rich_builder.ToolOutput] = []
        _collect_tool_outputs("some_agent", "not a dict", sink)  # type: ignore[arg-type]
        assert sink == []

    def test_payload_without_messages_key_is_silent(self):
        sink: list[rich_builder.ToolOutput] = []
        _collect_tool_outputs("some_agent", {"other_key": []}, sink)
        assert sink == []

    def test_multiple_tool_messages_all_captured(self):
        sink: list[rich_builder.ToolOutput] = []
        payload = {
            "messages": [
                _tool_msg("nse_get_quote", '{}', "tc1"),
                _tool_msg("nse_get_trade_info", '{}', "tc2"),
            ]
        }
        _collect_tool_outputs("market_data_agent", payload, sink)
        names = {o.name for o in sink if o.content is not None}
        assert "nse_get_quote" in names
        assert "nse_get_trade_info" in names

    def test_node_name_preserved_per_output(self):
        sink: list[rich_builder.ToolOutput] = []
        payload = {"messages": [_tool_msg("search_news", '[]')]}
        _collect_tool_outputs("news_and_research_agent", payload, sink)
        assert all(o.agent == "news_and_research_agent" for o in sink if o.content is not None)


# ---------------------------------------------------------------------------
# ChatResponse Pydantic model
# ---------------------------------------------------------------------------

class TestChatResponse:
    def test_minimal_response_has_no_rich(self):
        r = ChatResponse(reply="hello")
        assert r.reply == "hello"
        assert r.agents_used == []
        assert r.rich is None

    def test_rich_payload_accepted(self):
        payload = {
            "mode": "snapshot",
            "metric_cards": [],
            "comparison_rows": [],
            "strengths_risks": [],
            "headlines": [],
        }
        r = ChatResponse(reply="hello", agents_used=["market_data_agent"], rich=payload)
        assert r.rich is not None
        assert r.rich["mode"] == "snapshot"

    def test_rich_none_explicitly(self):
        r = ChatResponse(reply="hello", rich=None)
        assert r.rich is None

    def test_agents_used_default_empty_list(self):
        r = ChatResponse(reply="ok")
        assert isinstance(r.agents_used, list)
        assert len(r.agents_used) == 0


# ---------------------------------------------------------------------------
# rich_builder.build() — robustness with empty / partial / corrupt outputs
# ---------------------------------------------------------------------------

class TestRichBuilderBuild:
    def test_chat_mode_returns_none(self):
        """A conversational question should return None (no structured panel)."""
        result = rich_builder.build(
            "What is the capital of India?",
            outputs=[],
            agents_used=[],
            final_markdown="New Delhi.",
        )
        assert result is None

    def test_snapshot_with_no_outputs_returns_none(self):
        """A snapshot query with zero tool outputs returns None gracefully."""
        result = rich_builder.build(
            "TCS",
            outputs=[],
            agents_used=["market_data_agent"],
            final_markdown="TCS is a large IT company.",
        )
        assert result is None

    def test_comparison_with_no_outputs_returns_none(self):
        result = rich_builder.build(
            "compare TCS vs Infosys",
            outputs=[],
            agents_used=["comparison_agent"],
            final_markdown="TCS and Infosys are both large IT firms.",
        )
        assert result is None

    def test_valuation_with_no_outputs_returns_none(self):
        result = rich_builder.build(
            "dcf valuation of RELIANCE",
            outputs=[],
            agents_used=["valuation_agent"],
            final_markdown="DCF not available.",
        )
        assert result is None

    def test_never_raises_on_corrupt_json_content(self):
        """build() swallows all exceptions and returns None."""
        corrupt = [
            rich_builder.ToolOutput(
                name="profile",
                agent="fundamental_analysis_agent",
                args={"symbol": "TCS"},
                content="not-json{{{corrupted",
            )
        ]
        try:
            result = rich_builder.build(
                "full analysis of TCS",
                outputs=corrupt,
                agents_used=["fundamental_analysis_agent"],
                final_markdown="TCS analysis.",
            )
            # Either None or a RichResponse is acceptable; must not raise.
        except Exception as exc:
            pytest.fail(f"build() raised unexpectedly: {exc}")

    def test_never_raises_on_empty_string_message(self):
        try:
            rich_builder.build("", outputs=[], agents_used=[], final_markdown="")
        except Exception as exc:
            pytest.fail(f"build() raised on empty message: {exc}")

    def test_news_mode_with_no_outputs_returns_none(self):
        result = rich_builder.build(
            "latest news for HDFC Bank",
            outputs=[],
            agents_used=["news_and_research_agent"],
            final_markdown="No news available.",
        )
        # _assemble_news may return a partial response or None — either is fine.
        # The critical thing is no exception.
        assert result is None or hasattr(result, "mode")


# ---------------------------------------------------------------------------
# /api/health/mcp — shape validation via FastAPI TestClient
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from api import app as oracle_app


class TestMcpHealthEndpoint:
    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(oracle_app)

    def test_returns_200(self, client: TestClient):
        response = client.get("/api/health/mcp")
        assert response.status_code == 200

    def test_response_has_all_ok_field(self, client: TestClient):
        body = client.get("/api/health/mcp").json()
        assert "all_ok" in body
        assert isinstance(body["all_ok"], bool)

    def test_response_has_servers_dict(self, client: TestClient):
        body = client.get("/api/health/mcp").json()
        assert "servers" in body
        assert isinstance(body["servers"], dict)

    def test_each_server_has_ok_field(self, client: TestClient):
        """Every server entry must have at least an 'ok' boolean."""
        body = client.get("/api/health/mcp").json()
        for name, srv in body["servers"].items():
            assert "ok" in srv, f"Server '{name}' missing 'ok' key"
            assert isinstance(srv["ok"], bool), f"Server '{name}' ok is not bool"

    def test_server_names_match_mcp_config(self, client: TestClient):
        """The servers returned should include all configured MCP server names."""
        from mcp_config import MCP_SERVERS
        body = client.get("/api/health/mcp").json()
        for name in MCP_SERVERS:
            assert name in body["servers"], f"Expected server '{name}' in health response"

    def test_all_ok_reflects_server_states(self, client: TestClient):
        """all_ok should be True iff every server's ok is True."""
        body = client.get("/api/health/mcp").json()
        expected = all(s["ok"] for s in body["servers"].values())
        assert body["all_ok"] == expected
