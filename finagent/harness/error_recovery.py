"""Retry logic and degraded-mode research."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger("finagent.harness.error_recovery")


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay_s: float = 0.5,
) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:
            last = exc
            logger.warning("Attempt %s failed: %s", i + 1, exc)
            await asyncio.sleep(base_delay_s * (2**i))
    assert last is not None
    raise last
