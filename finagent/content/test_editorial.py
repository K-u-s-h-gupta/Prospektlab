from finagent.content.editorial import (
    contains_internal_language,
    review_article_package,
    sanitize_article_package,
    sanitize_public_text,
)
from finagent.content.flash_engine import build_insights_hub_html
from finagent.content_automation import ContentArticleFaq, ContentArticlePackage, ContentArticleSection


def _make_article() -> ContentArticlePackage:
    sections = [
        ContentArticleSection(
            heading="What changed in the latest results",
            paragraphs=[
                "According to the NSE filing, revenue grew 14% year on year while EBIT margin expanded 120 basis points, giving the quarter immediate publish urgency for investors tracking operating leverage.",
                "Management said in the exchange filing that demand stayed resilient across domestic and export channels, while order conversion improved through the quarter.",
            ],
            bullets=["Revenue growth stayed above 10%", "Margin expansion came from mix and cost control"],
        ),
        ContentArticleSection(
            heading="How the official disclosures frame demand",
            paragraphs=[
                "The BSE filing points to stronger execution in industrial and infrastructure-linked orders, with management commentary highlighting a healthier tender pipeline for the next two quarters.",
                "Transcript commentary suggests the company is prioritising profitable growth instead of volume at any cost, and the latest results already showed a 120-basis-point improvement in incremental margin profile.",
            ],
        ),
        ContentArticleSection(
            heading="Ownership, governance, and filing signals",
            paragraphs=[
                "Verified filings show promoter ownership remained stable through the latest reporting cycle, while recent annual report disclosures did not indicate a material change in auditor posture or board continuity.",
                "Public records also show no fresh governance shock in the reporting window, which reduces the chance that the earnings narrative is being flattered by a hidden control issue.",
            ],
        ),
        ContentArticleSection(
            heading="Balance sheet and cash flow implications",
            paragraphs=[
                "According to the annual report and exchange filing trail, working-capital discipline improved and operating cash conversion remained supportive even as growth accelerated.",
                "According to the filing trail, the latest results were not driven only by accounting gains; cash conversion stayed aligned with the reported operating outcome.",
            ],
        ),
        ContentArticleSection(
            heading="What could change the next few quarters",
            paragraphs=[
                "The concall transcript indicates that raw-material costs, tender timing, and customer budgets remain the main swing factors for FY27, even after the strong quarter.",
                "If execution stays on track, the current results update could matter beyond one quarter because it resets expectations for both margins and capital deployment over the next 2 to 4 quarters.",
            ],
        ),
        ContentArticleSection(
            heading="Why this update matters now",
            paragraphs=[
                "Results season compresses attention, so a filing that combines double-digit growth, higher margins, and visible order commentary deserves a fast publication decision according to the official exchange release.",
                "The official source mix here is strong enough to support publication because the article is grounded in exchange disclosures, transcript commentary, and public corporate records.",
            ],
        ),
    ]
    faqs = [
        ContentArticleFaq(question="What was the main headline from the quarter?", answer="The quarter combined revenue growth, margin expansion, and supportive management commentary from official exchange disclosures."),
        ContentArticleFaq(question="Why is the filing material?", answer="It changes the near-term operating narrative and gives investors a better read on demand, profitability, and execution risk."),
        ContentArticleFaq(question="What sources support the story?", answer="The analysis relies on NSE and BSE filings, annual-report disclosures, and management commentary from official transcript records."),
        ContentArticleFaq(question="What should readers watch next?", answer="Readers should track follow-through in margins, cash conversion, order execution, and any change in governance or auditor signals."),
    ]
    return ContentArticlePackage(
        slug="sample-results",
        title="ABC Q4 results show margin expansion and stronger demand",
        description="ABC's latest results show stronger revenue growth, better margins, and cleaner cash conversion, with the official filing trail supporting a more urgent publication call.",
        hero_eyebrow="Research Brief",
        hero_title="ABC results show why the quarter matters beyond one print",
        hero_summary="The latest results update combines stronger revenue growth, margin expansion, steadier ownership signals, and management commentary that makes the filing more relevant than a routine quarterly release.",
        audience="Indian investors and market researchers",
        keywords=["ABC results", "NSE filing", "BSE disclosure", "governance signals"],
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


def test_review_article_blocks_internal_and_advisory_language():
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
    assert review.total_score >= 90
    assert review.urgency_score >= 50


def test_build_insights_hub_html_avoids_internal_copy():
    html = build_insights_hub_html("insights").lower()

    assert "ai research hub" not in html
    assert "knowledge graph" not in html
    assert "8-phase research pipeline" not in html
