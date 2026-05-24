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

from finagent.harness.preflight import preflight_prompt_block
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


if __name__ == "__main__":
    main()
