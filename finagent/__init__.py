"""FinAgent — long-running financial research agent (ProspektLab).

The architecture spec lists a top-level ``harness.py`` alongside a ``harness/`` package; in
Python only the package is importable if both exist, so the long-running harness lives in
:mod:`finagent.harness` (see :class:`finagent.harness.orchestrator.Harness`).
"""

from dotenv import load_dotenv
import os
from pathlib import Path

# Load from the finagent directory's .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from finagent.settings import FinAgentSettings, load_settings

__all__ = ["FinAgentSettings", "load_settings", "__version__"]

__version__ = "0.1.0"
