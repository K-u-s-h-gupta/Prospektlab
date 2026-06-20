"""Canvas persistence and controller utilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from finagent.canvas.models import CanvasClaim, CanvasSource, InteractiveResearchCanvas, SwarmTaskStatus
from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.canvas.store")


class CanvasStore:
    """Simple JSONL store for the interactive canvas."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else finagent_data_path("canvas")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def save(self, canvas: InteractiveResearchCanvas) -> None:
        path = self._path(canvas.session_id)
        try:
            path.write_text(json.dumps(canvas.to_dict(), ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            logger.exception("[CANVAS] failed to save %s", canvas.session_id)

    def load(self, session_id: str) -> InteractiveResearchCanvas | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return InteractiveResearchCanvas(
                session_id=data["session_id"],
                query=data.get("query", ""),
                target=data.get("target", ""),
                status=data.get("status", "pending"),
                current_phase=data.get("current_phase", "plan"),
                phases=data.get("phases", ["plan", "enrich", "swarm", "verify", "synthesize", "export"]),
                tasks=[SwarmTaskStatus(**t) for t in data.get("tasks", [])],
                sections=[],  # simplified load
                contradictions=data.get("contradictions", []),
                gaps=data.get("gaps", []),
                citations=[CanvasSource(**c) for c in data.get("citations", [])],
                user_steers=data.get("user_steers", []),
                version=data.get("version", 1),
                memo_md=data.get("memo_md", ""),
            )
        except Exception:
            logger.exception("[CANVAS] failed to load %s", session_id)
            return None

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def list_sessions(self) -> list[str]:
        return [p.stem for p in self.root.glob("*.json")]


class CanvasController:
    """Handles user steering commands applied to a canvas."""

    def __init__(self, store: CanvasStore | None = None) -> None:
        self.store = store or CanvasStore()

    def apply_steer(self, canvas: InteractiveResearchCanvas, steer: dict[str, Any]) -> list[dict]:
        """Record a user steer and return any new subtasks it implies."""
        canvas.user_steers.append(steer)
        new_tasks: list[dict] = []
        command = (steer.get("command") or "").lower()

        if "governance" in command or "director" in command or "pledge" in command:
            new_tasks.append({
                "task_id": f"steer-gov-{canvas.version}",
                "agent_id": "governance_forensics",
                "objective": f"User requested deeper governance analysis: {steer.get('text', '')}",
                "priority": 5,
            })
        elif "compare" in command or "versus" in command or "vs" in command:
            peer = steer.get("peer") or "nearest peer"
            new_tasks.append({
                "task_id": f"steer-comp-{canvas.version}",
                "agent_id": "competitor_moat",
                "objective": f"User requested comparison with {peer}",
                "priority": 5,
            })
        elif "scenario" in command or "what if" in command or "what-if" in command:
            new_tasks.append({
                "task_id": f"steer-causal-{canvas.version}",
                "agent_id": "causal_war_gamer",
                "objective": f"User scenario: {steer.get('text', '')}",
                "priority": 5,
            })
        elif "valuation" in command or "dcf" in command:
            new_tasks.append({
                "task_id": f"steer-val-{canvas.version}",
                "agent_id": "valuation_modeler",
                "objective": f"User requested deeper valuation: {steer.get('text', '')}",
                "priority": 5,
            })
        else:
            new_tasks.append({
                "task_id": f"steer-gen-{canvas.version}",
                "agent_id": "news_sentiment",
                "objective": f"User follow-up: {steer.get('text', '')}",
                "priority": 5,
            })

        canvas.bump_version()
        self.store.save(canvas)
        return new_tasks


__all__ = ["CanvasStore", "CanvasController"]
