"""Tool dispatch scaffold: priority queue + cost tracking hooks."""

from __future__ import annotations

import heapq
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True)
class QueuedToolCall:
    priority: int
    enqueued_at: float = field(compare=False)
    name: str = field(compare=False)
    args: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass
class ToolCostTracker:
    totals: dict[str, float] = field(default_factory=dict)

    def record(self, tool_name: str, cost_usd: float) -> None:
        self.totals[tool_name] = self.totals.get(tool_name, 0.0) + cost_usd


class ModelToolDispatcher:
    def __init__(
        self,
        handlers: dict[str, Callable[..., Awaitable[Any]]],
        *,
        cost_tracker: ToolCostTracker | None = None,
    ) -> None:
        self.handlers = handlers
        self.cost_tracker = cost_tracker or ToolCostTracker()
        self._queue: list[QueuedToolCall] = []

    def enqueue(self, name: str, args: dict[str, Any] | None = None, *, priority: int = 10) -> None:
        heapq.heappush(
            self._queue,
            QueuedToolCall(priority=priority, enqueued_at=time.monotonic(), name=name, args=args or {}),
        )

    async def dispatch_next(self) -> Any:
        if not self._queue:
            raise RuntimeError("Tool queue empty")
        item = heapq.heappop(self._queue)
        handler = self.handlers.get(item.name)
        if handler is None:
            raise KeyError(f"No handler for tool {item.name}")
        result = await handler(**item.args)
        return result
