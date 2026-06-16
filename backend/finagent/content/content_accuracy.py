"""Accuracy guards for generated articles.

Pure, testable functions that catch the failure modes seen in evidence-light
generation:

  1. U+FFFD / mojibake leakage in public copy (e.g. "India�s").
  2. Ungrounded headline numbers — a hard stat in the title that is not backed
     by any sourced evidence claim or supplied source material.
  3. Logically broken visuals — placeholder "emphasis" charts that mix a real
     percentage with arbitrary 1.0 scores, self-declared illustrative charts,
     or charts with fewer than two distinct numeric values.
  4. Fabricated source URLs — invented attachment links with all-zero GUIDs or
     obviously synthetic paths.

No IO, no LLM. The editorial gate and the batch coercer both call these.
"""

from __future__ import annotations

import re
from typing import Any

# ── 1. Mojibake / replacement-char repair ────────────────────────────────────

_FFFD_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "India�s" -> "India's"  (mangled smart apostrophe before s/t/re/ve/ll/d/m)
    (re.compile(r"�(s|t|re|ve|ll|d|m)\b", re.I), "'\\1"),
    # "�" between word chars often a stray apostrophe.
    (re.compile(r"(?<=\w)�(?=\w)"), "'"),
    # Rupee glyph that decoded to the replacement char before a digit.
    (re.compile(r"�(?=\s?\d)"), "Rs "),
    # Anything left.
    (re.compile(r"�"), ""),
)


def repair_replacement_chars(text: str) -> str:
    out = text or ""
    if "�" not in out:
        return out
    for pattern, repl in _FFFD_REPLACEMENTS:
        out = pattern.sub(repl, out)
    return out


# ── 2. Number extraction + headline grounding ────────────────────────────────

# No leading sign: a hyphen between digits is a range/separator ("0-3%"),
# not a negative. Treating it as a minus mis-reads ranges as new stats.
_NUM_TOKEN_RE = re.compile(r"\d[\d,]*\.?\d*")


def extract_number_tokens(text: str) -> set[str]:
    """Normalised numeric tokens (commas stripped, trailing zeros trimmed)."""
    tokens: set[str] = set()
    for raw in _NUM_TOKEN_RE.findall(text or ""):
        norm = raw.replace(",", "")
        try:
            val = float(norm)
        except ValueError:
            continue
        # Canonical form: drop trailing .0 so "1.3" == "1.30".
        tokens.add(("%g" % val))
    return tokens


# Years and small ordinals are not "stats" — they routinely appear in titles
# (FY25, Q4, June 2025) without needing an evidence claim.
_TRIVIAL_NUMBERS = {"%g" % n for n in range(0, 5)} | {
    "%g" % y for y in range(1990, 2051)
}
_FY_QUARTER_RE = re.compile(r"\b(?:fy|q[1-4]|h[12])\s?\d{2,4}\b", re.I)


def ungrounded_headline_numbers(title: str, grounded_text: str) -> list[str]:
    """Numbers in the title absent from the grounded evidence text.

    `grounded_text` should be the concatenation of sourced layers only — the
    evidence-note claims and any supplied source material — NOT the model's own
    free prose or self-asserted metric blocks, which can carry the fabrication.
    Year/FY/quarter tokens are ignored.
    """
    title_clean = _FY_QUARTER_RE.sub(" ", title or "")
    title_nums = extract_number_tokens(title_clean) - _TRIVIAL_NUMBERS
    if not title_nums:
        return []
    grounded = extract_number_tokens(grounded_text or "")
    return sorted(n for n in title_nums if n not in grounded)


# ── 3. Visual validation ─────────────────────────────────────────────────────

_ILLUSTRATIVE_RE = re.compile(
    r"\b(illustrativ|not a numeric|emphasis map|not a scorecard|qualitative|"
    r"indicative only|schematic)\b",
    re.I,
)


def visual_issues(visual: Any) -> list[str]:
    """Return a list of reasons the visual is not a trustworthy data chart.

    Accepts either a pydantic model (with .note/.points/.value) or a dict.
    """
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    note = str(_get(visual, "note", "") or "")
    points = _get(visual, "points", []) or []
    values: list[float] = []
    for p in points:
        v = _get(p, "value", None)
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue

    reasons: list[str] = []
    if _ILLUSTRATIVE_RE.search(note):
        reasons.append("self_declared_illustrative")
    if len(values) < 2:
        reasons.append("too_few_numeric_points")
    else:
        distinct = set(round(v, 6) for v in values)
        if len(distinct) < 2:
            reasons.append("all_values_identical")
        else:
            # Placeholder pattern: a majority share one identical value while a
            # single outlier differs (e.g. [1.3, 1.0, 1.0, 1.0]).
            from collections import Counter
            counts = Counter(round(v, 6) for v in values)
            most_common_val, most_common_n = counts.most_common(1)[0]
            if most_common_n >= len(values) - 1 and len(values) >= 3:
                reasons.append("placeholder_uniform_values")
    return reasons


def filter_valid_visuals(visuals: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split visuals into (kept, dropped-with-reasons)."""
    kept: list[Any] = []
    dropped: list[dict[str, Any]] = []
    for v in visuals or []:
        issues = visual_issues(v)
        if issues:
            title = v.get("title") if isinstance(v, dict) else getattr(v, "title", "")
            dropped.append({"title": title, "reasons": issues})
        else:
            kept.append(v)
    return kept, dropped


# ── 4. Fabricated URL detection ──────────────────────────────────────────────

_FAKE_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"0{6,}"),                        # 000000000000 in a GUID
    re.compile(r"0000[-.]0000"),                # 0000-0000 zeroed GUID segments
    re.compile(r"\b([0-9a-f])\1{7,}\b", re.I),  # repeated hex run aaaaaaaa
    re.compile(r"example\.com|placeholder|sample-url|todo", re.I),
)


def is_suspect_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    return any(p.search(raw) for p in _FAKE_URL_PATTERNS)


# ── 5. Placeholder (non-numeric) metric values ───────────────────────────────

_PLACEHOLDER_VALUE_RE = re.compile(
    r"^\s*(disclosed|declared|trend disclosed|broad band( disclosed)?|"
    r"broadly stable|stable|provided|announced|reported|updated|outlined|"
    r"in focus|monitored|tracked|n\.?a\.?|na|tbd|to be disclosed|not disclosed|"
    r"under review|qualitative|various|multiple)\s*$",
    re.I,
)


_PLACEHOLDER_LEAD_RE = re.compile(
    r"^\s*(disclosed|declared|trend disclosed|broad band|broadly stable|stable|"
    r"provided|announced|reported|updated|outlined|in focus|monitored|tracked|"
    r"to be disclosed|not disclosed|under review|qualitative|various|multiple|"
    r"awaited|awaits|pending|see filing|refer)\b",
    re.I,
)


def is_placeholder_metric_value(value: str) -> bool:
    """True when a metric 'value' carries no real datum.

    Catches hedge values the model emits in data-light mode ("Disclosed",
    "Trend disclosed", "Disclosed in Q4 FY25", "Broad band disclosed"). Period
    tokens (Q4, FY25) are stripped before the numeric check so a bare period
    reference does not count as a real number.
    """
    text = (value or "").strip()
    if not text:
        return True
    # Remove quarter/fiscal-year period tokens before deciding if a real number exists.
    text_wo_period = _FY_QUARTER_RE.sub("", text)
    text_wo_period = re.sub(r"\b(?:q[1-4]|h[12]|fy)\b", "", text_wo_period, flags=re.I)
    has_real_number = bool(re.search(r"\d", text_wo_period))
    if has_real_number:
        return False
    # No real number left → placeholder if it leads with a hedge verb, fully
    # matches a known placeholder phrase, or is a short symbol-free fragment.
    if _PLACEHOLDER_LEAD_RE.match(text) or _PLACEHOLDER_VALUE_RE.match(text):
        return True
    return len(text.split()) <= 4 and not re.search(r"[₹$%]", text)


def placeholder_metrics(metrics: list[Any]) -> list[str]:
    """Labels of metrics whose value is a non-numeric placeholder."""
    out: list[str] = []
    for m in metrics or []:
        value = m.get("value") if isinstance(m, dict) else getattr(m, "value", "")
        label = m.get("label") if isinstance(m, dict) else getattr(m, "label", "")
        if is_placeholder_metric_value(str(value or "")):
            out.append(str(label or value))
    return out


def suspect_evidence_urls(evidence_notes: list[Any]) -> list[str]:
    """URLs in evidence notes that look fabricated."""
    out: list[str] = []
    for note in evidence_notes or []:
        url = note.get("source_url") if isinstance(note, dict) else getattr(note, "source_url", "")
        if is_suspect_url(str(url or "")):
            out.append(str(url))
    return out


# ── Deterministic repair (operates on the raw synthesis dict pre-validation) ──


def _repair_title(title: str, grounded_text: str) -> str:
    """Strip ungrounded numeric stats from the headline, keep it readable."""
    bad = ungrounded_headline_numbers(title, grounded_text)
    if not bad:
        return title
    out = title
    # Remove "<num>%", "<num> bps", "Rs <num>", or bare "<num>" tokens that are
    # not grounded, plus a trailing unit and any now-dangling connector.
    for num in bad:
        out = re.sub(
            rf"(?:Rs\.?\s*|₹\s*)?\b{re.escape(num)}\b\s*(%|per cent|percent|bps|crore|cr|lakh|bn|billion|trillion|x)?",
            "",
            out,
            flags=re.I,
        )
    out = re.sub(r"\s*[:,]\s*(?=[,:])", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" :,-")
    out = re.sub(r"\s+([:,])", r"\1", out)
    return out or title


def enforce_article_accuracy(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Clean a raw synthesis dict in place-ish; return (data, actions taken).

    - Drops visuals that are not trustworthy data charts.
    - Drops evidence notes whose URL looks fabricated.
    - Repairs a headline carrying an ungrounded numeric stat.
    Grounding text = evidence-note claims + timeline (the sourced layers).
    """
    actions: list[str] = []

    notes = data.get("evidence_notes") or []
    clean_notes = [n for n in notes if not (isinstance(n, dict) and is_suspect_url(str(n.get("source_url") or "")))]
    if len(clean_notes) != len(notes):
        actions.append(f"dropped {len(notes) - len(clean_notes)} fabricated-URL evidence note(s)")
    data["evidence_notes"] = clean_notes

    visuals = data.get("visuals") or []
    kept, dropped = filter_valid_visuals(visuals)
    # Dedup visuals that plot the same series (e.g. model + fundamentals revenue).
    deduped: list[Any] = []
    seen_sigs: set[tuple] = set()
    for v in kept:
        pts = v.get("points") if isinstance(v, dict) else getattr(v, "points", [])
        sig = tuple(round(float(p.get("value") if isinstance(p, dict) else getattr(p, "value", 0)), 2) for p in (pts or []))
        if sig and sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        deduped.append(v)
    if len(deduped) != len(kept):
        actions.append(f"deduped {len(kept) - len(deduped)} duplicate visual(s)")
    if dropped:
        actions.append(f"dropped {len(dropped)} broken visual(s): " + "; ".join(d["reasons"][0] for d in dropped))
    data["visuals"] = deduped

    metrics = data.get("metrics") or []
    real_metrics = [m for m in metrics if not (isinstance(m, dict) and is_placeholder_metric_value(str(m.get("value") or "")))]
    if len(real_metrics) != len(metrics):
        actions.append(f"dropped {len(metrics) - len(real_metrics)} placeholder metric(s) (e.g. 'Disclosed')")
    data["metrics"] = real_metrics

    grounded = " ".join(
        [str(n.get("claim") or "") for n in clean_notes if isinstance(n, dict)]
        + [
            " ".join(str(ev.get(k) or "") for k in ("date", "event", "detail"))
            for ev in (data.get("timeline") or [])
            if isinstance(ev, dict)
        ]
    )
    new_title = _repair_title(str(data.get("title") or ""), grounded)
    if new_title != data.get("title"):
        actions.append(f"repaired ungrounded headline: {data.get('title')!r} -> {new_title!r}")
        data["title"] = new_title

    return data, actions
