from finagent.content.editorial import (
    contains_internal_language,
    review_article_package,
    sanitize_article_package,
    sanitize_public_text,
)
from finagent.content.flash_engine import build_insights_hub_html
from finagent.content_automation import (
    ContentArticleEvidenceNote,
    ContentArticleFaq,
    ContentArticlePackage,
    ContentArticleSection,
    ContentArticleTakeaway,
)


def _make_article() -> ContentArticlePackage:
    sections = [
        ContentArticleSection(
            heading="What changed in the latest results",
            paragraphs=[
                "According to the NSE filing, revenue grew 14% year on year to Rs 6,820 crore while EBIT margin expanded 120 basis points to 18.4%, giving the quarter immediate publish urgency for investors who track operating leverage and execution discipline across cycles.",
                "Management said in the exchange filing that demand stayed resilient across domestic and export channels, with order conversion improving through the quarter and book-to-bill closing the period above 1.2x for the third consecutive quarter despite a soft April start.",
                "The concall transcript adds that the company is now seeing better pricing on long-cycle orders, supported by lower input costs and a calibrated 6% increase in headcount focused on revenue-yielding sales engineers rather than support roles.",
            ],
            bullets=["Revenue growth stayed above 10%", "Margin expansion came from mix and cost control"],
        ),
        ContentArticleSection(
            heading="How the official disclosures frame demand",
            paragraphs=[
                "The BSE filing points to stronger execution in industrial and infrastructure-linked orders, with management commentary highlighting a healthier tender pipeline for the next two quarters and a 9% YoY increase in active project sites.",
                "Transcript commentary suggests the company is prioritising profitable growth instead of volume at any cost, and the latest results already showed a 120-basis-point improvement in incremental margin profile that the exchange disclosure attributes to favourable mix shift.",
                "According to the annual report, average ticket size for new orders rose 11% YoY, lifting realised gross margin by roughly 60 basis points without any change to discount discipline communicated to channel partners.",
            ],
        ),
        ContentArticleSection(
            heading="Ownership, governance, and filing signals",
            paragraphs=[
                "Verified filings show promoter ownership remained stable at 54.2% through the latest reporting cycle, while recent annual report disclosures did not indicate a material change in auditor posture, board continuity, or related-party transaction concentration.",
                "Public records also show no fresh governance shock in the reporting window, which reduces the chance that the earnings narrative is being flattered by a hidden control issue or a one-time accounting reclassification noted late in the year.",
                "SEBI's own quarterly review file shows no fresh adjudication or show-cause notice against the company or its key managerial personnel, leaving the governance backdrop unchanged from the prior period.",
            ],
        ),
        ContentArticleSection(
            heading="Balance sheet and cash flow implications",
            paragraphs=[
                "According to the annual report and exchange filing trail, working-capital discipline improved with debtor days falling 6 days YoY and operating cash conversion remaining supportive even as growth accelerated above sector run-rate.",
                "According to the filing trail, the latest results were not driven only by accounting gains because cash conversion stayed aligned with the reported operating outcome, with operating cash flow of Rs 940 crore covering capex of Rs 320 crore comfortably.",
                "Net debt fell to Rs 410 crore from Rs 580 crore a year earlier, while average cost of debt eased 35 basis points after the recent rating affirmation by a domestic agency in April.",
            ],
        ),
        ContentArticleSection(
            heading="What could change the next few quarters",
            paragraphs=[
                "The concall transcript indicates that raw-material costs, tender timing, and customer budgets remain the main swing factors for FY27, even after the strong quarter, with management flagging a 4-6% input-price headwind if commodities re-accelerate.",
                "If execution stays on track, the current results update could matter beyond one quarter because it resets expectations for both margins and capital deployment over the next 2 to 4 quarters, particularly as the order book extends past 3.2x revenue cover.",
                "Analysts at one domestic broker have already lifted FY27 EPS estimates by 6% to Rs 52, citing better mix and the announced Rs 250 crore capex into capacity debottlenecking that should support a 9-10% volume run-rate in H2.",
            ],
        ),
        ContentArticleSection(
            heading="Why this update matters now",
            paragraphs=[
                "Results season compresses attention, so a filing that combines double-digit growth, higher margins, and visible order commentary deserves a fast publication decision according to the official exchange release that landed before market open.",
                "The official source mix here is strong enough to support publication because the article is grounded in exchange disclosures, transcript commentary, and public corporate records, with at least four independent filing-level data points reinforcing the directional read.",
                "On a relative basis, the stock now trades at 21x forward earnings against a 5-year mean of 23x, leaving room for re-rating only if next quarter delivers a similar margin print.",
            ],
        ),
    ]
    faqs = [
        ContentArticleFaq(question="What was the main headline from the quarter?", answer="The quarter combined revenue growth, margin expansion, and supportive management commentary from official exchange disclosures."),
        ContentArticleFaq(question="Why is the filing material?", answer="It changes the near-term operating narrative and gives investors a better read on demand, profitability, and execution risk."),
        ContentArticleFaq(question="What sources support the story?", answer="The analysis relies on NSE and BSE filings, annual-report disclosures, and management commentary from official transcript records."),
        ContentArticleFaq(question="What should readers watch next?", answer="Readers should track follow-through in margins, cash conversion, order execution, and any change in governance or auditor signals."),
    ]
    key_takeaways = [
        ContentArticleTakeaway(heading="Revenue grew 14%", detail="Top line crossed Rs 6,800 crore versus the Rs 6,500 crore Street estimate for the quarter."),
        ContentArticleTakeaway(heading="Margin step-up", detail="EBIT margin widened 120 basis points to 18.4 percent on mix and cost control."),
        ContentArticleTakeaway(heading="Cash conversion held", detail="Operating cash conversion stayed aligned with reported profit per the exchange filing trail."),
        ContentArticleTakeaway(heading="Order pipeline firmer", detail="Concall commentary points to a healthier tender pipeline over the next two quarters."),
    ]
    evidence_notes = [
        ContentArticleEvidenceNote(
            claim="Net profit rose 14% year on year to Rs 1,240 crore in the March quarter, per the NSE filing.",
            source_title="NSE results filing",
            source_url="https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        ),
        ContentArticleEvidenceNote(
            claim="EBIT margin widened 120 basis points to 18.4% on mix and cost control, per the BSE filing.",
            source_title="BSE results filing",
            source_url="https://www.bseindia.com/corporates/ann.html",
        ),
    ]
    return ContentArticlePackage(
        slug="sample-results",
        key_takeaways=key_takeaways,
        evidence_notes=evidence_notes,
        title="ABC Q4 net profit climbs 14% to ₹1,240 crore as margins widen 120 bps",
        description="ABC's latest results show stronger revenue growth, better margins, and cleaner cash conversion, with the official filing trail supporting a more urgent publication call.",
        hero_eyebrow="Research Brief",
        hero_title="ABC results show why the quarter matters beyond one print",
        hero_summary="The latest results update combines stronger revenue growth, margin expansion, steadier ownership signals, and management commentary that makes the filing more relevant than a routine quarterly release.",
        audience="Indian investors and market researchers",
        keywords=["ABC results", "NSE filing", "BSE disclosure", "governance signals"],
        narrative_lede=(
            "ABC reported a 14% rise in net profit to ₹1,240 crore for the March quarter, as EBIT margin "
            "widened 120 basis points to 18.4% and revenue crossed ₹6,800 crore, comfortably ahead of the "
            "₹6,500 crore the Street had pencilled in."
        ),
        market_context=(
            "The print lands with the Nifty 50 near 24,800 and the broader capital-goods index up 9% this quarter, "
            "as a recovering order pipeline and firmer 8.4% execution margins lift sentiment across the sector that "
            "ABC competes in against three larger listed peers."
        ),
        analyst_commentary=(
            "Analysts tracking the stock raised FY27 EPS estimates by 6% to ₹52 after the beat, with one brokerage "
            "lifting its target to ₹1,150 and arguing that a 120-basis-point margin step-up underpins a 21x forward "
            "multiple even after the 14% post-result rally."
        ),
        sections=sections,
        faqs=faqs,
        cta_label="Talk to ProspektLab",
        cta_href="/#/contact",
        image_prompt="Editorial market publication cover",
    )


def test_sanitize_public_text_rewrites_internal_terms():
    text = "IKG and the 8-phase research pipeline from OpenAI power this AI-generated article."

    cleaned = sanitize_public_text(text)

    assert "IKG" not in cleaned
    assert "OpenAI" not in cleaned
    assert "AI-generated" not in cleaned
    assert "research workflow" in cleaned or "multi-step" in cleaned


def test_sanitize_article_package_removes_internal_language():
    article = _make_article()
    article.title = "IKG flagged a regulatory shift"
    article.sections[0].heading = "What the knowledge graph says"
    article.sections[0].paragraphs[0] = "The IKG says investors should buy after this quarter."

    sanitized = sanitize_article_package(article)

    assert not contains_internal_language(sanitized.title)
    assert not contains_internal_language(sanitized.sections[0].heading)
    assert not contains_internal_language(sanitized.sections[0].paragraphs[0])


def test_review_article_blocks_internal_and_advisory_language(monkeypatch):
    # Force strict (non-RA) compliance so advisory language carries the full
    # compliance penalty regardless of the developer's local env.
    monkeypatch.setenv("FINAGENT_COMPLIANCE_MODE", "strict")
    article = _make_article()
    article.sections[0].paragraphs[0] = "The IKG says this stock is a strong buy after the quarter."

    review = review_article_package(article)

    assert review.ready_to_publish is False
    codes = {issue.code for issue in review.issues}
    assert "advisory_language" in codes


def test_review_article_can_clear_strong_article():
    article = _make_article()

    review = review_article_package(article)

    assert review.ready_to_publish is True
    # Composite rescaled after adding the LiveMint narrative dimension (weight 0.15).
    assert review.total_score >= 88
    assert review.urgency_score >= 50
    assert review.livemint_score >= 70


def test_review_blocks_when_livemint_source_leaks():
    article = _make_article()

    review = review_article_package(article, livemint_source_violations=2)

    assert review.ready_to_publish is False
    codes = {issue.code for issue in review.issues}
    assert "livemint_source_leak" in codes
    # Compliance must take the 45-point hit when a Livemint URL slips through.
    assert review.compliance_score <= 55


def test_review_blocks_official_story_under_900_words():
    article = _make_article()
    # Shrink the story below 900 words while preserving section count.
    for section in article.sections:
        section.paragraphs = [section.paragraphs[0][:60]]
        section.bullets = []
    article.narrative_lede = "Short."
    article.market_context = "Short."
    article.analyst_commentary = "Short."

    review = review_article_package(article, is_official_source=True, evidence_claim_count=3)

    assert review.ready_to_publish is False
    codes = {issue.code for issue in review.issues}
    assert "official_article_too_short" in codes


def test_review_blocks_when_evidence_claims_are_missing():
    article = _make_article()

    review = review_article_package(article, evidence_claim_count=0)

    codes = {issue.code for issue in review.issues}
    assert "missing_evidence_claims" in codes
    assert review.ready_to_publish is False


def test_review_records_quality_score():
    article = _make_article()

    review = review_article_package(article, quality_score=80)

    assert review.quality_score == 80
    assert review.word_count > 0


def test_build_insights_hub_html_avoids_internal_copy():
    html = build_insights_hub_html("insights").lower()

    assert "ai research hub" not in html
    assert "knowledge graph" not in html
    assert "8-phase research pipeline" not in html
