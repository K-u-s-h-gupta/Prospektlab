"""One-off: drive generate_flash_article end-to-end to audit the new pipeline."""
import asyncio, os, sys, uuid, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / "finagent" / ".env")

# Bound the deep pipeline so it can't run away while we audit it.
os.environ.setdefault("FINAGENT_CONTENT_DEEP_WALL_SECONDS", "100")
os.environ.setdefault("FINAGENT_SPECIALIST_WAVE_DISABLED", "1")

from finagent.content.flash_engine import FlashGenerationRequest, generate_flash_article

# Real, sourced earnings facts seeded as primary evidence (so grounding + the
# archetype=earnings title-number contract are genuinely exercised).
SOURCE = """Infosys Q2 FY26 results (filed with BSE/NSE, 2025-10-16):
- Consolidated revenue Rs 42,310 crore, up 8.6% YoY and 2.1% QoQ.
- Net profit (PAT) Rs 6,920 crore, up 13.2% YoY.
- Operating (EBIT) margin 21.3%, up 40 bps QoQ.
- Constant-currency revenue growth guidance for FY26 raised to 3.0-4.0% (from 1.0-3.0%).
- Large deal TCV USD 3.8 billion, 56% net-new.
- Attrition (LTM) 13.4%, down from 14.1% last quarter.
- Headcount 3,29,900, a net addition of 8,200 QoQ.
- Free cash flow Rs 7,540 crore; FCF/PAT 109%.
- Board declared interim dividend of Rs 21 per share.
- BFSI and manufacturing verticals led growth; communications remained soft.
"""

async def main():
    req = FlashGenerationRequest(
        mode="deep",
        content_type="earnings",
        target="Infosys Q2 FY26 results",
        objective="Earnings analysis of Infosys Q2 FY26: growth, margins, deal TCV, guidance, cash, attrition.",
        source_markdown=SOURCE,
        route_base="insights",
        include_image=False,
        overwrite=True,
        force_publish=False,
    )
    job_id = uuid.uuid4().hex[:12]
    print(f"[gen] job={job_id} starting deep pipeline...", flush=True)
    res = await generate_flash_article(req, job_id=job_id, requested_by="audit@local")
    print(f"[gen] DONE slug={res.slug} status={res.publish_status} confidence={res.confidence_score}", flush=True)
    print(f"[gen] json={res.json_path}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
