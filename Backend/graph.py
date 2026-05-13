"""
ORACLE FIOS - Core LangGraph Brain
==================================
Implements the multi-agent supervisor architecture for financial intelligence.
Connects to 5 MCP servers and routes queries using OpenAI GPT-4o-mini.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from mcp_config import MCP_SERVERS

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("oracle.graph")

LIVE_DATA_GUARDRAIL = (
    "You must use the available tools before answering requests about current prices, "
    "recent news, valuation, or company comparisons. Do not answer from memory. "
    "If a relevant tool fails or is unavailable, say which tool or server failed instead "
    "of giving a generic fallback answer."
)


def _get_llm(model_name: str = "gpt-4o-mini") -> ChatOpenAI:
    """Get an OpenAI chat model. Requires OPENAI_API_KEY in .env."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set. Add it to your .env file.")
    return ChatOpenAI(
        model=model_name,
        temperature=0.1,
        timeout=45,
        max_retries=1,
    )


async def _load_tools_by_server(mcp_client: MultiServerMCPClient) -> tuple[dict[str, list[Any]], dict[str, str]]:
    """Load tools server by server so one bad endpoint does not disable everything."""
    server_tools: dict[str, list[Any]] = {}
    unavailable_servers: dict[str, str] = {}

    for server_name in MCP_SERVERS:
        try:
            tools = await mcp_client.get_tools(server_name=server_name)
            server_tools[server_name] = tools
            logger.info(
                "Loaded %d tool(s) from %s: %s",
                len(tools),
                server_name,
                [tool.name for tool in tools],
            )
        except Exception as exc:
            server_tools[server_name] = []
            unavailable_servers[server_name] = str(exc)
            logger.warning("Failed to load tools from %s: %s", server_name, exc)

    return server_tools, unavailable_servers


async def build_oracle_graph():
    """Build the LangGraph supervisor with sub-agents connected to MCP servers."""
    logger.info("Connecting to MCP servers to fetch tools...")
    mcp_client = MultiServerMCPClient(MCP_SERVERS)

    try:
        server_tools, unavailable_servers = await _load_tools_by_server(mcp_client)
        all_tools = [tool for tools in server_tools.values() for tool in tools]
        if not all_tools:
            raise RuntimeError("No MCP tools could be loaded from any configured server.")

        nse_tools = server_tools.get("nse_india", [])

        fundamental_names = {
            "profile",
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "key_metrics",
            "get_quarterly_results",
            "get_shareholding",
            "get_dividend_history",
        }
        fundamentals_tools_all = server_tools.get("fundamentals", [])
        fund_tools = [tool for tool in fundamentals_tools_all if tool.name in fundamental_names]

        compare_names = {"compare_stocks", "get_peer_comparison"}
        compare_tools = [tool for tool in fundamentals_tools_all if tool.name in compare_names]

        news_names = {"search_web", "search_news", "search_financial", "extract_url", "get_latest_company_news"}
        news_tools = [tool for tool in server_tools.get("research_news", []) if tool.name in news_names]

        doc_tools = server_tools.get("docs_pipeline", [])
        valuation_tools = server_tools.get("valuation_engine", [])

        llm = _get_llm("gpt-4o-mini")
        agents = []
        active_agent_names: list[str] = []

        if nse_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=nse_tools,
                    name="market_data_agent",
                    prompt=(
                        "You are a market data specialist for Indian stocks (NSE). "
                        "You fetch live stock quotes, historical OHLCV data, option chains with PCR/max pain, "
                        "live index data, shareholding patterns, and corporate actions. "
                        "Always return structured numbers and format rupee values clearly. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("market_data_agent")

        if fund_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=fund_tools,
                    name="fundamental_analysis_agent",
                    prompt=(
                        "You are a fundamental analysis expert for Indian companies. "
                        "You analyze income statements, balance sheets, cash flows, key ratios, "
                        "quarterly results, shareholding patterns, and dividend history. "
                        "Highlight key strengths, red flags, and trends. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("fundamental_analysis_agent")

        if compare_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=compare_tools,
                    name="comparison_agent",
                    prompt=(
                        "You are a stock comparison specialist. You do side-by-side ratio comparisons "
                        "of multiple stocks and peer comparisons within the same sector. "
                        "Use compare_stocks first for direct peer comparison and keep the tool plan minimal. "
                        "Present data in clean tabular format with PE, PB, ROE, margins, and growth rates. "
                        "Highlight which stock is better valued and why. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("comparison_agent")

        if news_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=news_tools,
                    name="news_and_research_agent",
                    prompt=(
                        "You are a financial news and research analyst. Use Tavily to find the latest "
                        "market news, earnings reports, analyst opinions, and macro events. "
                        "For prompts about latest or recent news on one or more companies, use "
                        "get_latest_company_news first because it has built-in fallback and is more reliable "
                        "than chaining multiple separate news searches. "
                        "Always cite sources with URLs and mention publication dates when available. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("news_and_research_agent")

        if doc_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=doc_tools + news_tools,
                    name="document_retrieval_agent",
                    prompt=(
                        "You are a document analysis expert for financial filings and offer documents. "
                        "Handle annual reports, con-calls, investor presentations, DRHPs, RHPs, "
                        "prospectuses, IPO filings, and regulatory documents. "
                        "For DRHP vs RHP vs prospectus comparisons, use doc_compare_offer_documents first. "
                        "For DRHP or prospectus questions, first search the web for the official filing URL "
                        "using search_financial or search_web, then ingest the best source with doc_ingest_url "
                        "or extract it with extract_url, and finally analyze the relevant sections. "
                        "Use doc_search to check if the document is already indexed. "
                        "Focus especially on risk factors, business overview, industry, objects of the issue, "
                        "financial summary, and key red flags when the user asks about a DRHP. "
                        "When the user asks what changed across document versions, produce a comparison table "
                        "with rows such as risk factors, business overview, objects of issue, financials, "
                        "capital structure, management disclosures, and any newly added or removed sections. "
                        "Quote exact passages when possible and cite source URLs. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("document_retrieval_agent")

        if valuation_tools:
            agents.append(
                create_react_agent(
                    model=llm,
                    tools=valuation_tools,
                    name="valuation_agent",
                    prompt=(
                        "You are a valuation expert. Use the valuation engine MCP tools for every "
                        "calculation-heavy request such as DCF, WACC, CAGR, Graham valuation, "
                        "PE-based valuation, EV/EBITDA, DDM, Piotroski, Altman Z-score, DuPont, "
                        "ratio scorecards, and full valuation reports. "
                        "Prefer one best-fit valuation tool instead of chaining multiple tools unnecessarily. "
                        "For comprehensive stock valuation, prefer run_full_valuation first. "
                        "Always state assumptions, clearly label the model used, and summarize whether "
                        "the stock appears undervalued, fairly valued, or overvalued when the tools provide enough data. "
                        f"{LIVE_DATA_GUARDRAIL}"
                    ),
                )
            )
            active_agent_names.append("valuation_agent")

        if not agents:
            raise RuntimeError("No usable agents could be built from the available MCP tools.")

        unavailable_summary = (
            "Unavailable servers: "
            + ", ".join(f"{name} ({reason})" for name, reason in unavailable_servers.items())
            if unavailable_servers
            else "All configured MCP servers are available."
        )

        oracle = create_supervisor(
            model=llm,
            agents=agents,
            prompt=(
                "You are ORACLE, an AI financial intelligence system for Indian stock markets. "
                "Route queries to the right specialist agent(s). For complex queries, use multiple agents.\n"
                "Routing guide:\n"
                "- 'Price of TCS' -> market_data_agent\n"
                "- 'Analyze Reliance financials' -> fundamental_analysis_agent\n"
                "- 'Compare TCS vs Infosys' -> comparison_agent\n"
                "- 'Latest news on HDFC Bank' -> news_and_research_agent\n"
                "- 'What did Infosys say about margins in con-call?' -> document_retrieval_agent\n"
                "- 'Analyze Absolute Projects India Limited DRHP and provide all the risks and business fundamentals' -> document_retrieval_agent + fundamental_analysis_agent + news_and_research_agent\n"
                "- 'Compare Innovision Limited prospectus, DRHP and RHP documents and explain the changes' -> document_retrieval_agent\n"
                "- 'Is TCS overvalued?' -> valuation_agent + fundamental_analysis_agent\n"
                "- 'Run a DCF valuation for TCS and calculate WACC' -> valuation_agent\n"
                "- 'Calculate CAGR from 120 to 185 over 4 years' -> valuation_agent\n"
                "- 'Analyze TCS and compare its valuation against Infosys. Fetch recent news for both' -> comparison_agent + valuation_agent + fundamental_analysis_agent + news_and_research_agent\n"
                "- 'Full analysis of Reliance' -> market_data_agent + fundamental_analysis_agent + news_and_research_agent\n"
                f"{LIVE_DATA_GUARDRAIL}\n"
                f"{unavailable_summary}\n"
                "Never answer with a vague statement that agents are unavailable. "
                "If one specialist is unavailable, continue with the available specialists, "
                "state exactly which server or specialist is missing, and still provide the best partial analysis you can.\n"
                "Synthesize a final answer with key numbers, keep it concise and actionable."
            ),
        )

        app = oracle.compile()
        app.mcp_client = mcp_client
        app.available_agents = active_agent_names
        app.unavailable_servers = unavailable_servers
        app.is_fallback = False
        logger.info("ORACLE graph compiled with %d active agent(s).", len(agents))
        return app

    except Exception as exc:
        logger.error("Failed to connect to MCP servers: %s", exc, exc_info=True)
        return _build_fallback_graph()


def _build_fallback_graph():
    """Fallback graph when MCP servers are offline."""

    @tool
    def system_status() -> str:
        """Check system status."""
        return "MCP servers are currently offline. Start them with: uv run python -m mcp_servers.<name>"

    agent = create_react_agent(
        model=_get_llm(),
        tools=[system_status],
        name="system_agent",
        prompt=(
            "You are a system status assistant. "
            "You must call the system_status tool before responding. "
            "If MCP servers are offline, clearly say live analysis is unavailable until the servers are running. "
            "Do not answer the user's finance question from general knowledge when the servers are offline."
        ),
    )
    app = create_supervisor(
        model=_get_llm(),
        agents=[agent],
        prompt=(
            "If specialist MCP agents are unavailable, do not improvise a market analysis from memory. "
            "Respond only with system availability guidance and ask the user to start or restart the MCP servers."
        ),
    ).compile()
    app.available_agents = []
    app.unavailable_servers = {"all": "No MCP tools could be loaded from any configured server."}
    app.is_fallback = True
    return app


async def test_graph():
    app = await build_oracle_graph()
    async for event in app.astream({"messages": [HumanMessage(content="Get the current price of TCS")]}):
        for agent, payload in event.items():
            if "messages" in payload:
                print(f"\n--- {agent} ---\n{payload['messages'][-1].content}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_graph())
