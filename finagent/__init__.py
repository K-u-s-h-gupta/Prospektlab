"""FinAgent — long-running financial research agent (ProspektLab).

The architecture spec lists a top-level ``harness.py`` alongside a ``harness/`` package; in
Python only the package is importable if both exist, so the long-running harness lives in
:mod:`finagent.harness` (see :class:`finagent.harness.orchestrator.Harness`).
"""

# ---------------------------------------------------------------------------
# Fix: curl_cffi (used by yfinance) cannot encode CA cert paths containing
# non-ASCII characters (e.g. Hindi directory names on Windows).
# This patch must run before yfinance or curl_cffi is imported anywhere.
# ---------------------------------------------------------------------------
import os
import shutil
import tempfile
try:
    import certifi
    _safe_cacert = os.path.join(tempfile.gettempdir(), "cacert.pem")
    try:
        _safe_cacert.encode('ascii')
    except UnicodeEncodeError:
        _safe_cacert = "C:\\temp\\cacert.pem"
        os.makedirs("C:\\temp", exist_ok=True)
    if not os.path.exists(_safe_cacert):
        shutil.copy2(certifi.where(), _safe_cacert)
    os.environ["CURL_CA_BUNDLE"] = _safe_cacert
    os.environ["REQUESTS_CA_BUNDLE"] = _safe_cacert
    os.environ["SSL_CERT_FILE"] = _safe_cacert
except Exception:
    pass
# ---------------------------------------------------------------------------

from dotenv import load_dotenv
from pathlib import Path

# Load from the finagent directory's .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

from finagent.settings import FinAgentSettings, load_settings

__all__ = ["FinAgentSettings", "load_settings", "__version__"]

__version__ = "0.1.0"
