"""Deep semantic output scrubber — runs AFTER enforce_sebi_compliance().

Scans both prose text AND embedded JSON blocks for advisory language that
slipped through the first-pass compliance filter.  Every replacement is
logged to a per-session compliance audit trail stored in JSONL format under
FINAGENT_AUDIT_DIR (defaults to ./audit_logs/).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.output.scrubber")

# ── Directory for audit trail JSONL files ────────────────────────────────────
_AUDIT_DIR = Path(os.getenv("FINAGENT_AUDIT_DIR", "audit_logs"))


# ── Patterns that survive the first-pass compliance filter ───────────────────
# Ordered most-to-least specific.

_DEEP_PHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JSON key patterns — "verdict": "STRONG BUY" style
    (re.compile(r'"verdict"\s*:\s*"[^"]*"', re.I), '"scenario_assessment": "model output assessed under stated assumptions"'),
    # Residual label strings that may appear as JSON values
    (re.compile(r'"STRONG\s+BUY"', re.I), '"favorable_under_stated_assumptions"'),
    (re.compile(r'"BUY"', re.I), '"positive_scenario_under_assumptions"'),
    (re.compile(r'"SELL"', re.I), '"negative_scenario_under_assumptions"'),
    (re.compile(r'"STRONG\s+SELL"', re.I), '"highly_negative_scenario_under_assumptions"'),
    (re.compile(r'"HOLD"', re.I), '"monitor_under_assumptions"'),
    (re.compile(r'"AVOID"', re.I), '"unfavorable_scenario_under_assumptions"'),
    (re.compile(r'"UNDERVALUED"', re.I), '"below_model_implied_value"'),
    (re.compile(r'"OVERVALUED"', re.I), '"above_model_implied_value"'),
    (re.compile(r'"FAIRLY\s+VALUED"', re.I), '"near_model_implied_value"'),
    # Prose patterns — directional language combined with ticker/company references
    (re.compile(r'\b(this is a (?:good|great|excellent|strong)\s+(?:buy|investment|opportunity))\b', re.I),
     "the model outputs show favorable signals under stated assumptions"),
    (re.compile(r'\b(investors?\s+(?:should|must|ought to)\s+(?:buy|sell|invest|exit|accumulate|avoid))\b', re.I),
     "investors should review the evidence and risk profile with a SEBI-registered adviser"),
    (re.compile(r'\b(we\s+(?:recommend|suggest)\s+(?:buying|selling|holding|accumulating))\b', re.I),
     "the evidence indicates"),
    # Density patterns — "X is a buy" without "model" qualifier
    (re.compile(r'\b(?:is|looks|appears|seems)\s+(?:a\s+)?(?:strong\s+buy|buy|sell|undervalued|overvalued)\b', re.I),
     "shows scenario-conditional signals under stated assumptions"),
)

_NOISE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\[SOURCE:[^\]]+\]", re.I), ""),
    (re.compile(r"\[AS-OF:[^\]]+\]", re.I), ""),
    (re.compile(r"\[CONFIDENCE:\s*(?:HIGH|MEDIUM|LOW|DERIVED)\s*\]", re.I), ""),
    (re.compile(r"(?im)^\s*Regulatory note:.*$"), ""),
    (re.compile(r"(?im)^\s*This is informational analysis, not investment advice\..*$"), ""),
    (re.compile(r"(?im)^\s*Sources consulted:\s*\d+\s*$"), ""),
)

# ── JSON key names that carry advisory meaning ───────────────────────────────
_ADVISORY_JSON_KEYS: frozenset[str] = frozenset({
    "verdict", "recommendation", "investment_recommendation", "action",
})

_SAFE_REPLACEMENT_VALUE = "assessed_under_stated_assumptions"


@dataclass
class ScrubAction:
    scrub_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    pattern: str = ""
    original: str = ""
    replacement: str = ""
    context_chars: str = ""   # 50-char window around the match


@dataclass
class ScrubResult:
    text: str
    actions: list[ScrubAction] = field(default_factory=list)
    json_keys_renamed: int = 0

    @property
    def clean(self) -> bool:
        return not self.actions and self.json_keys_renamed == 0


def _scrub_json_block(obj: Any, actions: list[ScrubAction]) -> Any:
    """Recursively scrub advisory keys from a parsed JSON object."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            new_key = "scenario_assessment" if k.lower() in _ADVISORY_JSON_KEYS else k
            if new_key != k:
                action = ScrubAction(
                    pattern=f"json_key:{k}",
                    original=k,
                    replacement=new_key,
                    context_chars=str(v)[:50],
                )
                actions.append(action)
            # Also scrub the value itself if it's a string
            if new_key == "scenario_assessment" and isinstance(v, str):
                v = _SAFE_REPLACEMENT_VALUE
            out[new_key] = _scrub_json_block(v, actions)
        return out
    if isinstance(obj, list):
        return [_scrub_json_block(item, actions) for item in obj]
    return obj


def _extract_and_scrub_json_blocks(text: str, actions: list[ScrubAction]) -> tuple[str, int]:
    """Find fenced JSON blocks in markdown, scrub them, and return updated text."""
    json_key_renames = 0
    json_fence_pattern = re.compile(r"```(?:json)?\s*\n([\s\S]*?)\n```", re.M)

    def _replace_json(match: re.Match[str]) -> str:
        nonlocal json_key_renames
        raw_json = match.group(1)
        try:
            obj = json.loads(raw_json)
            before_count = len(actions)
            scrubbed_obj = _scrub_json_block(obj, actions)
            json_key_renames += len(actions) - before_count
            return f"```json\n{json.dumps(scrubbed_obj, indent=2, ensure_ascii=False)}\n```"
        except json.JSONDecodeError:
            return match.group(0)  # Leave unparseable blocks alone

    new_text = json_fence_pattern.sub(_replace_json, text)
    return new_text, json_key_renames


def scrub_output(text: str, *, session_id: str | None = None) -> ScrubResult:
    """Run deep semantic scrub on generated finance prose.

    Args:
        text: The raw output text (markdown or plain text) to be scrubbed.
        session_id: Optional session identifier for the audit trail.

    Returns:
        ScrubResult with the cleaned text and list of all actions taken.
    """
    if not text:
        return ScrubResult(text=text)

    out = text
    actions: list[ScrubAction] = []

    # Pass 1: Scrub embedded JSON blocks
    out, json_key_renames = _extract_and_scrub_json_blocks(out, actions)

    # Pass 2: Deep regex scan of prose
    for pattern, replacement in _DEEP_PHRASE_PATTERNS:
        for match in list(pattern.finditer(out)):
            start = max(0, match.start() - 25)
            end = min(len(out), match.end() + 25)
            ctx = out[start:end]
            action = ScrubAction(
                pattern=pattern.pattern[:60],
                original=match.group(0),
                replacement=replacement,
                context_chars=ctx,
            )
            actions.append(action)
        out = pattern.sub(replacement, out)

    # Pass 3: Strip repetitive non-informative boilerplate/noisy markers.
    for pattern, replacement in _NOISE_PATTERNS:
        for match in list(pattern.finditer(out)):
            start = max(0, match.start() - 25)
            end = min(len(out), match.end() + 25)
            ctx = out[start:end]
            actions.append(
                ScrubAction(
                    pattern=pattern.pattern[:60],
                    original=match.group(0),
                    replacement=replacement,
                    context_chars=ctx,
                )
            )
        out = pattern.sub(replacement, out)

    out = re.sub(r"\n{3,}", "\n\n", out).strip()

    result = ScrubResult(text=out, actions=actions, json_keys_renamed=json_key_renames)

    if actions or json_key_renames:
        _write_audit_trail(result, session_id=session_id)

    return result


def _write_audit_trail(result: ScrubResult, *, session_id: str | None = None) -> None:
    """Append scrub actions to a JSONL audit log file."""
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _AUDIT_DIR / f"scrub_audit_{time.strftime('%Y%m%d')}.jsonl"
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id or "unknown",
            "json_keys_renamed": result.json_keys_renamed,
            "phrase_replacements": len(result.actions) - result.json_keys_renamed,
            "actions": [
                {
                    "id": a.scrub_id,
                    "pattern": a.pattern,
                    "original": a.original[:120],
                    "replacement": a.replacement[:120],
                    "context": a.context_chars[:100],
                }
                for a in result.actions
            ],
        }
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(
            "[SCRUBBER] Logged %d scrub actions (json_keys=%d) to %s",
            len(result.actions),
            result.json_keys_renamed,
            log_file,
        )
    except Exception as exc:
        logger.warning("[SCRUBBER] Failed to write audit trail: %s", exc)


def scrub_and_comply(text: str, *, session_id: str | None = None) -> str:
    """Convenience wrapper: enforce_sebi_compliance → scrub_output → return text.

    Use this as the single entry-point in the agent pipeline.
    """
    from finagent.output.compliance import enforce_sebi_compliance

    # First pass: deterministic regex compliance
    after_compliance = enforce_sebi_compliance(text, include_regulatory_note=False)
    # Second pass: deeper semantic scan
    result = scrub_output(after_compliance, session_id=session_id)
    return result.text
