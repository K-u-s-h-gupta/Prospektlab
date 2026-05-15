from __future__ import annotations

import os
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_paths() -> list[Path]:
    workspace_home = repo_root() / ".finagent"
    temp_home = Path(tempfile.gettempdir()) / "finagent"
    if str(workspace_home).isascii():
        return [workspace_home, temp_home]
    return [temp_home, workspace_home]


def _ensure_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def finagent_home() -> Path:
    override = (os.getenv("FINAGENT_HOME") or "").strip()
    if override:
        home = Path(override).expanduser()
        home.mkdir(parents=True, exist_ok=True)
        return home
    for candidate in _candidate_paths():
        if _ensure_writable(candidate):
            return candidate
    fallback = repo_root() / ".finagent"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def finagent_data_path(*parts: str) -> Path:
    path = finagent_home().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
