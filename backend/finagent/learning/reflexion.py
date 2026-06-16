"""Reflexion Feedback Loop — post-grader lesson extraction.

After grader flags are produced, routes each flag to the responsible agent type.
Each agent writes a one-paragraph lesson that is stored in memory Tier 2.
The 3 most recent relevant lessons are loaded per agent at session start.

Reference: "Reflexion: Language Agents with Verbal Reinforcement Learning"
           (Shinn et al., 2023) — https://arxiv.org/abs/2303.11366
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("finagent.learning.reflexion")


@dataclass
class ReflexionLesson:
    """A lesson learned from a grader flag."""
    agent_type: str        # e.g. "governance", "valuation", "synthesis"
    flag_code: str         # e.g. "PLEDGE_NOT_ADDRESSED"
    lesson_text: str       # One-paragraph lesson
    entity_name: str = ""
    sector: str | None = None
    session_id: str | None = None
    created_at: float = 0.0


_FLAG_TO_AGENT: dict[str, str] = {
    "SEBI_ADVISORY_LANGUAGE": "synthesis",
    "NO_SOURCES": "synthesis",
    "LOW_SOURCE_COVERAGE": "synthesis",
    "PLEDGE_NOT_ADDRESSED": "governance",
    "IMPLICIT_ASSUMPTIONS": "valuation",
    "NO_SCENARIO_FRAMING": "synthesis",
    "INTERNAL_CONTRADICTION": "synthesis",
    "WACC_CONSISTENCY": "valuation",
}


async def extract_lessons_from_flags(
    grader_flags: list[dict[str, Any]],
    synthesis_output: str,
    *,
    entity_name: str = "",
    sector: str | None = None,
    session_id: str | None = None,
) -> list[ReflexionLesson]:
    """Extract lessons from grader flags using LLM.

    Args:
        grader_flags: List of GraderFlag dicts (code, severity, message, responsible_agent).
        synthesis_output: The synthesis text that was graded.
        entity_name: Company researched.
        sector: SEBI sector.
        session_id: Session identifier.

    Returns:
        List of ReflexionLessons, one per unique agent_type with flags.
    """
    if not grader_flags:
        return []

    # Group flags by responsible agent
    agent_flags: dict[str, list[dict[str, Any]]] = {}
    for flag in grader_flags:
        agent = flag.get("responsible_agent") or _FLAG_TO_AGENT.get(flag.get("code", ""), "synthesis")
        agent_flags.setdefault(agent, []).append(flag)

    lessons: list[ReflexionLesson] = []
    for agent_type, flags in agent_flags.items():
        lesson_text = await _generate_lesson(
            agent_type=agent_type,
            flags=flags,
            synthesis_snippet=synthesis_output[:800],
            entity_name=entity_name,
        )
        if lesson_text:
            lessons.append(ReflexionLesson(
                agent_type=agent_type,
                flag_code=",".join(f.get("code", "") for f in flags[:3]),
                lesson_text=lesson_text,
                entity_name=entity_name,
                sector=sector,
                session_id=session_id,
                created_at=time.time(),
            ))

    logger.info(
        "[REFLEXION] Generated %d lessons for entity=%s",
        len(lessons), entity_name,
    )
    return lessons


async def _generate_lesson(
    agent_type: str,
    flags: list[dict[str, Any]],
    synthesis_snippet: str,
    entity_name: str,
) -> str:
    """Use LLM to write a one-paragraph lesson for the agent type."""
    from finagent.runtime_provider import resolve_openai_config

    cfg = resolve_openai_config(complexity="simple")
    if not cfg:
        # Fallback: template-based lesson
        flag_msgs = "; ".join(f.get("message", "") for f in flags[:2])
        return (
            f"For {agent_type} analysis of {entity_name or 'this type of company'}: "
            f"Previous session flagged: {flag_msgs}. "
            f"Next time, explicitly address these issues before finalizing output."
        )

    flag_summary = "\n".join(
        f"- {f.get('code')}: {f.get('message', '')}" for f in flags
    )

    prompt = f"""You are reviewing quality flags from a {agent_type} research agent.

Entity researched: {entity_name or 'unknown company'}
Quality flags received:
{flag_summary}

Snippet of the flagged output:
{synthesis_snippet[:400]}

Write ONE concise paragraph (2-3 sentences) as a lesson for the {agent_type} agent.
The lesson should be specific and actionable for future similar research sessions.
Focus on: what went wrong, what to do differently next time.
Do NOT use advisory language (buy/sell). Do NOT repeat the entity name unnecessarily."""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=10.0)
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": "You write concise research quality improvement lessons."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_completion_tokens=150,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.debug("[REFLEXION] LLM lesson generation failed: %s", exc)
        flag_msgs = "; ".join(f.get("message", "") for f in flags[:2])
        return f"Review flagged issues: {flag_msgs}. Address these in future {agent_type} analysis."


async def store_lessons(
    lessons: list[ReflexionLesson],
    memory_store: Any | None = None,
    user_email: str | None = None,
) -> int:
    """Store reflexion lessons in tiered memory Tier 2 (recall memories).

    Args:
        lessons: List of ReflexionLesson objects.
        memory_store: ProspektTieredMemoryStore instance.
        user_email: User email for memory scoping.

    Returns:
        Number of lessons stored.
    """
    if not lessons:
        return 0

    stored = 0

    if memory_store and user_email:
        for lesson in lessons:
            try:
                await memory_store.remember(
                    target_key=f"reflexion:{lesson.agent_type}",
                    kind="reflexion_lesson",
                    body=lesson.lesson_text,
                    confidence="HIGH",
                    session_id=lesson.session_id,
                    user_email=user_email,
                    metadata={
                        "agent_type": lesson.agent_type,
                        "flag_code": lesson.flag_code,
                        "entity_name": lesson.entity_name,
                        "sector": lesson.sector,
                    },
                )
                stored += 1
            except Exception as exc:
                logger.warning("[REFLEXION] Failed to store lesson: %s", exc)
    else:
        # Log to file as fallback
        log_dir = "reflexion_logs"
        os.makedirs(log_dir, exist_ok=True)
        import json
        log_file = os.path.join(log_dir, f"lessons_{time.strftime('%Y%m%d')}.jsonl")
        with open(log_file, "a", encoding="utf-8") as fh:
            for lesson in lessons:
                fh.write(json.dumps({
                    "agent_type": lesson.agent_type,
                    "flag_code": lesson.flag_code,
                    "lesson": lesson.lesson_text,
                    "entity": lesson.entity_name,
                    "sector": lesson.sector,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lesson.created_at)),
                }) + "\n")
            stored = len(lessons)

    logger.info("[REFLEXION] Stored %d lessons", stored)
    return stored


async def load_recent_lessons(
    agent_type: str,
    memory_store: Any | None = None,
    user_email: str | None = None,
    limit: int = 3,
) -> list[str]:
    """Load the N most recent relevant lessons for an agent type.

    Args:
        agent_type: Agent type to load lessons for.
        memory_store: ProspektTieredMemoryStore instance.
        user_email: User email for memory scoping.
        limit: Maximum lessons to load.

    Returns:
        List of lesson text strings.
    """
    if not memory_store or not user_email:
        return []

    try:
        facts = await memory_store.query_facts(
            user_email=user_email,
            target_key=f"reflexion:{agent_type}",
            kind="reflexion_lesson",
            limit=limit,
        )
        return [f.get("body", "") for f in facts if f.get("body")]
    except Exception as exc:
        logger.debug("[REFLEXION] Failed to load lessons for %s: %s", agent_type, exc)
        return []


def format_lessons_for_context(lessons: list[str], agent_type: str) -> str:
    """Format lessons as context block for agent prompt injection."""
    if not lessons:
        return ""
    lines = [
        f"## Lessons from Previous {agent_type.title()} Research",
        "Apply these insights from past research sessions:",
        "",
    ]
    for i, lesson in enumerate(lessons, 1):
        lines.append(f"{i}. {lesson}")
        lines.append("")
    return "\n".join(lines)
