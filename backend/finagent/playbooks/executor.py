from __future__ import annotations

import re

from finagent.playbooks.schema import FinancialPlaybook


def _target_tokens(target_label: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (target_label or "").lower())
        if token not in {"india", "limited", "ltd", "inc", "corp", "company"}
    }


def _rewrite_template(template: str, *, target_label: str, example_target: str) -> str:
    rendered = (template or "").strip()
    if not rendered:
        return ""
    if "{target}" in rendered or "{target_label}" in rendered:
        return (
            rendered
            .replace("{target_label}", target_label)
            .replace("{target}", target_label)
            .strip()
        )
    if example_target:
        pattern = re.compile(re.escape(example_target), flags=re.IGNORECASE)
        match = pattern.search(rendered)
        rewritten = pattern.sub(target_label, rendered).strip()
        if rewritten != rendered and match is not None:
            # Legacy templates often include the old ticker right after the
            # company name ("Adani Power Limited ADANIPOWER ..."). Drop that
            # stale ticker token after we rewrite the entity label.
            suffix = rendered[match.end():].strip()
            stale_token = suffix.split()[0] if suffix else ""
            if re.fullmatch(r"[A-Z0-9.]{2,12}", stale_token or ""):
                rewritten = re.sub(
                    rf"^{re.escape(target_label)}\s+{re.escape(stale_token)}\b",
                    target_label,
                    rewritten,
                    flags=re.IGNORECASE,
                ).strip()
            return rewritten
    # Legacy playbooks without placeholders are unsafe to replay across entities.
    return ""


def apply_playbook_to_queries(
    queries: list[str],
    playbook: FinancialPlaybook | None,
    *,
    target_label: str = "",
    max_extra: int = 2,
) -> list[str]:
    if playbook is None:
        return queries
    safe_target = (target_label or "").strip()
    token_guard = _target_tokens(safe_target)
    out = list(queries)
    appended = 0
    for q in playbook.query_templates:
        if appended >= max_extra:
            break
        candidate = _rewrite_template(
            q,
            target_label=safe_target,
            example_target=(playbook.example_target or "").strip(),
        )
        if not candidate:
            continue
        lowered = candidate.lower()
        if token_guard and not any(token in lowered for token in token_guard):
            continue
        if candidate in out:
            continue
        out.append(candidate)
        appended += 1
    return out
