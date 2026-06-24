"""Tests for archetype classification + grounded-title anchoring."""

from finagent.content.archetype import classify_archetype, title_anchor_ok


# ── classify_archetype: >=1 case per archetype ───────────────────────────────

def test_classify_personnel():
    assert classify_archetype(
        "ABC Ltd", "company", "The CFO has resigned with immediate effect."
    ) == "personnel"


def test_classify_personnel_reverse_order():
    assert classify_archetype(
        "XYZ", "manual", "Board appointed a new managing director on Monday."
    ) == "personnel"


def test_classify_regulatory():
    assert classify_archetype(
        "Promoter probe", "sebi", "SEBI passed an adjudication order and a penalty."
    ) == "regulatory"


def test_classify_regulatory_from_content_type():
    # content_type 'sebi' alone routes to regulatory.
    assert classify_archetype("Some Co", "sebi", "details of the matter") == "regulatory"


def test_classify_ma():
    assert classify_archetype(
        "DEF", "manual", "The board approved the merger and a share buyback."
    ) == "ma"


def test_classify_rating():
    assert classify_archetype(
        "GHI Ltd", "company", "ICRA announced a rating downgrade on the long-term debt."
    ) == "rating"


def test_classify_earnings():
    assert classify_archetype(
        "TCS", "earnings", "Q4 FY25 results: revenue and PAT both rose."
    ) == "earnings"


def test_classify_trend():
    assert classify_archetype(
        "IT sector", "trend", "The macro outlook for the sector amid rate cuts."
    ) == "trend"


def test_classify_company_fallback():
    assert classify_archetype(
        "JKL Industries", "company", "A profile of the firm's business lines."
    ) == "company"


# ── title_anchor_ok: pass + fail per key archetype ───────────────────────────

def test_personnel_pass():
    ok, code = title_anchor_ok(
        "ABC CFO resigns with immediate effect",
        "personnel",
        "The chief financial officer of ABC resigned, the company told the exchange.",
    )
    assert ok is True
    assert code == ""


def test_personnel_fail_no_action():
    ok, code = title_anchor_ok(
        "ABC CFO in the spotlight this quarter",
        "personnel",
        "The chief financial officer of ABC spoke at the concall.",
    )
    assert ok is False
    assert code == "personnel_no_action"


def test_personnel_pass_grounded_name_without_role():
    ok, code = title_anchor_ok(
        "Sharma resigns from the board",
        "personnel",
        "Rajeev Sharma resigned from the board, the filing said.",
    )
    assert ok is True


def test_regulatory_pass():
    ok, code = title_anchor_ok(
        "SEBI bars promoter in adjudication order",
        "regulatory",
        "SEBI passed an adjudication order barring the promoter from the market.",
    )
    assert ok is True
    assert code == ""


def test_regulatory_fail_no_regulator():
    ok, code = title_anchor_ok(
        "Promoter barred in fresh order",
        "regulatory",
        "An order barred the promoter.",
    )
    assert ok is False
    assert code == "regulatory_no_regulator"


def test_earnings_pass():
    ok, code = title_anchor_ok(
        "ABC Q4 net profit climbs 14% to Rs 1,240 crore",
        "earnings",
        "Net profit rose 14% to Rs 1,240 crore in the March quarter per the NSE filing.",
    )
    assert ok is True
    assert code == ""


def test_earnings_fail_no_number():
    # The real audit case: a number-free earnings title must be rejected.
    ok, code = title_anchor_ok(
        "TCS Q4 FY25: revenue, margins and dividend keep investor focus on FY26 demand",
        "earnings",
        "TCS reported its fourth-quarter results.",
    )
    assert ok is False
    assert code == "title_no_number"


def test_earnings_fail_ungrounded_number():
    ok, code = title_anchor_ok(
        "ABC Q4 net profit climbs 99% to Rs 9,999 crore",
        "earnings",
        "Net profit rose 14% to Rs 1,240 crore in the March quarter.",
    )
    assert ok is False
    assert code == "title_ungrounded_number"


def test_vague_trend_title_rejected():
    ok, code = title_anchor_ok(
        "Evolving landscape keeps investor focus on a robust outlook",
        "trend",
        "The IT sector outlook remains in focus.",
    )
    assert ok is False
    assert code == "vague_title"


def test_company_title_with_concrete_subject_passes():
    ok, code = title_anchor_ok(
        "Infosys deepens its 35% cloud revenue mix",
        "company",
        "Infosys derives 35% of revenue from cloud, the annual report shows.",
    )
    assert ok is True


def test_unknown_archetype_does_not_block():
    ok, code = title_anchor_ok("Anything goes here", "", "grounded")
    assert ok is True
