"""FinAgent — long-running financial research agent (ProspektLab).

The architecture spec lists a top-level ``harness.py`` alongside a ``harness/`` package; in
Python only the package is importable if both exist, so the long-running harness lives in
:mod:`finagent.harness` (see :class:`finagent.harness.orchestrator.Harness`).
"""

from finagent.settings import FinAgentSettings, load_settings

__all__ = ["FinAgentSettings", "load_settings", "__version__"]

__version__ = "0.1.0"
