"""One-off script: generate and publish the Britannia 3QFY25 article
from the HSIE PDF source, using flash_engine's deep mode with all
quality/urgency/source-density gates enforced."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

PDF_PATH = Path(r"C:\Users\kusha\Downloads\Britannia - 3QFY25 - HSIE-202502080823269652745.pdf")


def extract_pdf_text(pdf_path: Path) -> str:
    import pypdf
    reader = pypdf.PdfReader(str(pdf_path))
    chunks = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text()
        except Exception:
            continue
        if text:
            chunks.append(f"--- Page {i + 1} ---\n{text}")
    return "\n\n".join(chunks)


async def main() -> None:
    if not PDF_PATH.exists():
        print(f"PDF not found: {PDF_PATH}")
        return

    print(f"Extracting PDF: {PDF_PATH.name}")
    full_text = extract_pdf_text(PDF_PATH)
    print(f"Extracted {len(full_text)} chars across {full_text.count('--- Page')} pages")

    if len(full_text) > 28000:
        full_text = full_text[:28000]

    from finagent.content.flash_engine import (
        FlashGenerationRequest,
        generate_flash_article,
    )

    req = FlashGenerationRequest(
        mode="research",
        content_type="earnings",
        target="Britannia Industries",
        objective=(
            "Generate a publication-grade research analysis of Britannia Industries' 3QFY25 results based "
            "on the verified HSIE Research note attached as source. Cover: volume vs margin trade-off, "
            "raw material inflation impact on gross margin, segmental performance (biscuits, adjacencies, "
            "international), management's pricing strategy and distribution expansion thesis, valuation, "
            "and forward-looking watchpoints. Write in LiveMint / Hindu BusinessLine register."
        ),
        source_markdown=full_text,
        route_base="insights",
        include_image=True,
        overwrite=True,
        force_publish=False,
    )

    print("\nStarting flash_engine generation (deep mode, all gates enforced)...")
    result = await generate_flash_article(
        req,
        job_id="britannia-3qfy25",
        requested_by="manual_generation",
    )

    print("\n=== RESULT ===")
    print(f"Slug:           {result.slug}")
    print(f"Title:          {result.title}")
    print(f"Publish status: {result.publish_status}")
    print(f"Confidence:     {result.confidence_score}")
    print(f"Public URL:     {result.public_url}")
    print(f"HTML path:      {result.html_path}")
    if hasattr(result, "review_reason") and result.review_reason:
        print(f"Review reason:  {result.review_reason}")


if __name__ == "__main__":
    asyncio.run(main())
