from __future__ import annotations

from finagent.output.contracts import OutputMode


SECTION_TEMPLATES: dict[OutputMode, list[str]] = {
    OutputMode.DIRECT_ANSWER: ["Answer", "Sources"],
    OutputMode.COMPANY_SNAPSHOT: ["Quick Take", "Key Metrics", "Business", "Recent Developments", "Main Risks", "Sources"],
    OutputMode.COMPANY_COMPARISON: ["Key Takeaways", "Side-by-Side Comparison", "Valuation and Quality", "Risks", "Evidence-Based View", "Sources"],
    OutputMode.VALUATION_MODEL: ["Valuation Summary", "Assumptions", "Model Output", "Sensitivity", "Caveats", "Sources"],
    OutputMode.NEWS_BRIEF: ["Top Stories", "Why It Matters", "Market Impact", "Sources"],
    OutputMode.FILING_ANALYSIS: ["Business Overview", "Issue / Filing Details", "Risk Factors", "Financials", "Red Flags", "Sources"],
    OutputMode.DOCUMENT_VERSION_COMPARISON: ["Summary", "Version Comparison", "Disclosure Changes", "Red Flags", "Sources"],
    OutputMode.INVESTMENT_VIEW: ["Evidence-Based View", "Constructive Scenario", "Adverse Scenario", "What Would Change The View", "Sources"],
    OutputMode.MARKET_EXPLAINER: ["Short Answer", "India Market Context", "Impact", "What To Track", "Sources"],
    OutputMode.DEEP_RESEARCH_REPORT: [
        "Executive Summary",
        "Research Plan and Scope",
        "Company and Business Model",
        "Financial Profile",
        "Valuation and Sensitivity",
        "Competitive Position",
        "Risks and Red Flags",
        "Macro and Sector Overlay",
        "Catalysts and Watchlist",
        "Bull Case, Bear Case, Base Case",
        "Evidence Quality and Limitations",
        "Sources",
    ],
}

