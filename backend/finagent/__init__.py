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

from dotenv import dotenv_values, load_dotenv
from pathlib import Path

# Load root .env first, then backend/finagent/.env so package-local defaults can
# override repo defaults without clobbering real process/container environment.
_package_dir = Path(__file__).parent
_root_env_path = _package_dir.parent / ".env"
_package_env_path = _package_dir / ".env"
if _root_env_path.exists() or _package_env_path.exists():
    _merged_env: dict[str, str] = {}
    if _root_env_path.exists():
        _merged_env.update(
            {k: v for k, v in dotenv_values(_root_env_path).items() if v is not None}
        )
    if _package_env_path.exists():
        _merged_env.update(
            {k: v for k, v in dotenv_values(_package_env_path).items() if v is not None}
        )
    for _env_key, _env_value in _merged_env.items():
        os.environ.setdefault(_env_key, _env_value)
else:
    load_dotenv(override=True)

# Supabase exposes Postgres. If only SUPABASE_DB_URL is present, wire the
# existing Postgres code path automatically instead of falling back to memory.
_db_url = (
    os.getenv("IKG_DATABASE_URL", "").strip()
    or os.getenv("DATABASE_URL", "").strip()
    or os.getenv("SUPABASE_DB_URL", "").strip()
)
if _db_url:
    os.environ.setdefault("IKG_DATABASE_URL", _db_url)
    os.environ.setdefault("DATABASE_URL", _db_url)
    os.environ.setdefault("SUPABASE_DB_URL", _db_url)
    os.environ.setdefault("IKG_BACKEND", "postgres")

from finagent.settings import FinAgentSettings, load_settings

__all__ = ["FinAgentSettings", "load_settings", "__version__"]

__version__ = "0.1.0"
