"""CLI entry for FinAgent."""

from __future__ import annotations

import os
import sys

# Fix Windows UTF-8 before any imports (crawl4ai's Rich logger crashes on cp1252)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import argparse
import asyncio
import json

from finagent.harness.preflight import preflight_prompt_block
from finagent.content_automation import (
    ContentAutomationBatchRequest,
    ContentAutomationBatchTopic,
    ContentEventIngestionRequest,
    ContentAutomationRequest,
    generate_article_automation,
    generate_article_batch,
    ingest_market_event_triggers,
)
from finagent.research_planner import build_default_plan
from finagent.run_agent import AgentLoopConfig, run_research_session


def main() -> None:
    p = argparse.ArgumentParser(prog="finagent")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight", help="Print mandatory pre-flight questions")
    pf.set_defaults(func=_cmd_preflight)

    rs = sub.add_parser("run-stub", help="Run stub research loop (no LLM)")
    rs.add_argument("--target", required=True)
    rs.add_argument("--objective", required=True)
    rs.add_argument("--max-steps", type=int, default=50)
    rs.set_defaults(func=_cmd_run_stub)

    gc = sub.add_parser("generate-content", help="Generate one automated article")
    gc.add_argument("--topic", required=True)
    gc.add_argument("--slug")
    gc.add_argument("--company-symbol")
    gc.add_argument("--search-query")
    gc.add_argument("--source-url")
    gc.add_argument("--source-markdown")
    gc.add_argument("--audience", default="Indian investors and market researchers")
    gc.add_argument("--route-base", default="insights")
    gc.add_argument("--no-image", action="store_true")
    gc.add_argument("--no-public-mirror", action="store_true")
    gc.add_argument("--no-overwrite", action="store_true")
    gc.set_defaults(func=_cmd_generate_content)

    gb = sub.add_parser("generate-content-batch", help="Generate articles from a JSON config")
    gb.add_argument("--config", required=True, help="Path to JSON config file")
    gb.set_defaults(func=_cmd_generate_content_batch)

    ge = sub.add_parser("ingest-event-triggers", help="Poll BSE/NSE/SEBI triggers and generate articles")
    ge.add_argument("--config", required=True, help="Path to JSON event watch config")
    ge.set_defaults(func=_cmd_ingest_event_triggers)

    args = p.parse_args()
    args.func(args)


def _cmd_preflight(_: argparse.Namespace) -> None:
    print(preflight_prompt_block())


def _cmd_run_stub(args: argparse.Namespace) -> None:
    plan = build_default_plan(args.target, args.objective)
    print(plan.to_prompt_block())
    pl, cp = asyncio.run(
        run_research_session(
            args.target,
            args.objective,
            plan=plan,
            loop_config=AgentLoopConfig(max_steps=args.max_steps),
        )
    )
    print("--- checkpoint step", cp.step, "completed", len(cp.completed_steps))


def _cmd_generate_content(args: argparse.Namespace) -> None:
    req = ContentAutomationRequest(
        topic=args.topic,
        slug=args.slug,
        company_symbol=args.company_symbol,
        search_query=args.search_query,
        source_url=args.source_url,
        source_markdown=args.source_markdown,
        audience=args.audience,
        publish_to_frontend_public=not args.no_public_mirror,
        include_image=not args.no_image,
        overwrite=not args.no_overwrite,
        route_base=args.route_base,
    )
    result = asyncio.run(generate_article_automation(req, requested_by="cli"))
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=True))


def _cmd_generate_content_batch(args: argparse.Namespace) -> None:
    with open(args.config, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if isinstance(raw, dict) and "topics" in raw:
        req = ContentAutomationBatchRequest.model_validate(raw)
    elif isinstance(raw, list):
        req = ContentAutomationBatchRequest(topics=[ContentAutomationBatchTopic.model_validate(item) for item in raw])
    else:
        raise SystemExit("Batch config must be either a list of topic objects or an object with a 'topics' array.")

    result = asyncio.run(generate_article_batch(req, requested_by="cli-batch"))
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=True))


def _cmd_ingest_event_triggers(args: argparse.Namespace) -> None:
    with open(args.config, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    req = ContentEventIngestionRequest.model_validate(raw)
    result = asyncio.run(ingest_market_event_triggers(req, requested_by="cli-events"))
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
