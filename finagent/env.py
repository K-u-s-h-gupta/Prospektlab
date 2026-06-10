"""Shared environment loading for local and deployed FinAgent processes."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_finagent_env() -> None:
    """Load root and package .env files without overriding process env vars."""
    package_dir = Path(__file__).resolve().parent
    repo_root = package_dir.parent
    load_dotenv(repo_root / ".env", override=False)
    load_dotenv(package_dir / ".env", override=False)
