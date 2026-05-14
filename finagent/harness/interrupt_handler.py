"""Mid-session interrupt handling (Section 2.5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class InterruptChoice(str, Enum):
    CONTINUE = "continue"
    REDIRECT = "redirect"
    ABANDON = "abandon"


@dataclass
class InterruptResolution:
    choice: InterruptChoice
    new_instruction: str | None = None


async def handle_interrupt(
    message: str,
    ask_human: Callable[[str], Awaitable[InterruptResolution]],
    *,
    pause_current_step: Callable[[], Awaitable[None]],
    resume_from_checkpoint: Callable[[], Awaitable[None]],
    replan_from_current_state: Callable[[str], Awaitable[None]],
    save_final_checkpoint: Callable[[], Awaitable[None]],
) -> None:
    await pause_current_step()
    options = await ask_human(
        f"Interrupt received: {message}\n"
        "Choose: (a) continue (b) redirect with new instruction (c) abandon session."
    )
    if options.choice == InterruptChoice.CONTINUE:
        await resume_from_checkpoint()
    elif options.choice == InterruptChoice.REDIRECT:
        if not options.new_instruction:
            raise ValueError("redirect requires new_instruction")
        await replan_from_current_state(options.new_instruction)
    else:
        await save_final_checkpoint()
