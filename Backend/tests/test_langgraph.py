import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph import build_oracle_graph
from langchain_core.messages import HumanMessage


def _safe_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return " ".join(parts)
    return str(content)


async def main():
    print("=" * 60)
    print("ORACLE FIOS - LangGraph Supervisor Test")
    print("=" * 60)
    print("\nAttempting to build graph and connect to MCP servers...")

    app = await build_oracle_graph()
    query = "Analyze TCS and compare its valuation against Infosys. Fetch recent news for both."
    print(f"\n[User Query]: {query}")
    print("\nStreaming agent events...\n")

    seen_agents = set()
    async for event in app.astream({"messages": [HumanMessage(content=query)]}, subgraphs=True):
        if isinstance(event, tuple):
            _, payload = event
        else:
            payload = event

        if not isinstance(payload, dict):
            continue

        for node_name, node_payload in payload.items():
            agent_name = node_name.split(":", 1)[0] if isinstance(node_name, str) else str(node_name)
            if agent_name in {"__start__", "__end__"}:
                continue
            seen_agents.add(agent_name)

            if isinstance(node_payload, dict) and node_payload.get("messages"):
                content = _safe_text(getattr(node_payload["messages"][-1], "content", ""))
                if content:
                    preview = content.encode("ascii", "backslashreplace").decode()
                    print(f"[{agent_name}] {preview[:240]}")

    print("\nAgents seen:", ", ".join(sorted(seen_agents)))


if __name__ == "__main__":
    asyncio.run(main())
