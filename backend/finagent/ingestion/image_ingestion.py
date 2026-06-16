from __future__ import annotations

import base64
import json
import logging
import os

from finagent.ingestion.portfolio_schema import (
    PortfolioExtractionLLMResponse,
    PortfolioExtractionSchema,
)

logger = logging.getLogger("finagent.ingestion.image_ingestion")

_HOLDINGS_SCREEN_LABELS = (
    "holdings",
    "portfolio",
    "positions",
    "invested",
    "current value",
    "market value",
    "qty",
    "quantity",
    "ltp",
    "nav",
    "p&l",
    "day p&l",
)


class PortfolioImageExtractionError(RuntimeError):
    pass


def _mime_type(filename: str) -> str:
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext in {"jpg", "jpeg"}:
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    return "application/octet-stream"


async def extract_portfolio_from_image(image_bytes: bytes, filename: str) -> PortfolioExtractionSchema:
    """Extract holdings from a genuine broker holdings screenshot using OpenAI vision."""
    if not image_bytes:
        raise PortfolioImageExtractionError("Image upload is empty.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable not set; cannot extract from image")
        raise PortfolioImageExtractionError(
            "OPENAI_API_KEY environment variable is required for screenshot extraction. "
            "Set it in your .env file or environment."
        )

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise PortfolioImageExtractionError("openai package is not installed.") from exc

    data_url = f"data:{_mime_type(filename)};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    client = AsyncOpenAI(api_key=api_key)
    model = os.getenv("PORTFOLIO_VISION_MODEL", "gpt-5.4-mini")

    prompt = (
        "First decide whether this image is a genuine Indian broker or DP holdings screenshot. "
        "Classify screen_type as 'portfolio_holdings' only when the image clearly shows a holdings or portfolio screen with security rows and portfolio columns. "
        "If the image is random, unrelated, or not a holdings view, set screen_type='not_portfolio', positions=[], visible_labels=[], rejection_reason, and confidence<=0.2. "
        "If the image is blurry or uncertain, set screen_type='unclear', positions=[], visible_labels=[], rejection_reason, and confidence<=0.3. "
        "When the image is valid, extract ONLY visible holdings from this Indian broker or DP portfolio screenshot. "
        "Supported brokers include Zerodha, Groww, Dhan, Shoonya, Angel, Motilal, Axis Direct, and similar Indian broker holdings views. "
        "Also return visible_labels[] with the exact UI labels you can clearly read, like Holdings, Qty, Invested, Current Value, Day P&L, Market Value. "
        "Extract these fields per row: symbol, quantity, price_or_nav, market_value, cost_basis, and name. "
        "Indian number formatting must be normalized to exact numeric JSON values. "
        "Do not infer or hallucinate missing grid values. If a value is not visible, omit it or use 0. "
        "Each position must include symbol, quantity, market_value, confidence, and raw_evidence copied from visible text. "
        "Use exchange 'NSE' for stocks unless the screenshot clearly shows BSE, and 'AMFI' for mutual funds. "
        "Return JSON with status='REVIEW_REQUIRED', source_type='image', screen_type, visible_labels, rejection_reason, positions[], warnings[]. "
        "Never convert a random screen, article, invoice, chat, gallery image, or photo into holdings rows."
    )

    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        parser = getattr(getattr(client, "beta", None), "chat", None)
        parse_completions = getattr(getattr(parser, "completions", None), "parse", None) if parser else None
        if parse_completions:
            response = await parse_completions(
                model=model,
                temperature=0,
                messages=messages,
                response_format=PortfolioExtractionLLMResponse,
            )
            llm_result: PortfolioExtractionLLMResponse | None = response.choices[0].message.parsed
            if llm_result is None:
                content = response.choices[0].message.content or "{}"
                llm_result = PortfolioExtractionLLMResponse.model_validate(json.loads(content))
        else:
            response = await client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            llm_result = PortfolioExtractionLLMResponse.model_validate(json.loads(content))
    except Exception as exc:
        logger.exception("OpenAI screenshot extraction failed")
        raise PortfolioImageExtractionError(f"Screenshot extraction failed: {exc}") from exc

    extraction = PortfolioExtractionSchema(
        status=llm_result.status,
        source_type=llm_result.source_type,
        broker_or_vendor=llm_result.broker_or_vendor,
        positions=llm_result.positions,
        warnings=llm_result.warnings,
        confidence=llm_result.confidence,
    )

    visible_labels = [" ".join(str(label or "").split()) for label in llm_result.visible_labels if str(label or "").strip()]
    holdings_label_hits = sum(
        1 for label in visible_labels if any(term in label.lower() for term in _HOLDINGS_SCREEN_LABELS)
    )
    strong_positions = sum(
        1
        for position in extraction.positions
        if (position.symbol or position.name or position.isin or position.amfi)
        and (position.quantity > 0 or position.market_value > 0)
    )

    if (
        llm_result.screen_type != "portfolio_holdings"
        or strong_positions == 0
        or extraction.confidence < 0.45
        or (holdings_label_hits == 0 and not (extraction.broker_or_vendor or "").strip())
    ):
        reason = llm_result.rejection_reason.strip() or (
            "This screenshot is not a verified holdings screen. Upload a broker holdings page that clearly shows securities, quantities, and values."
        )
        raise PortfolioImageExtractionError(reason)

    extraction.status = "REVIEW_REQUIRED"
    extraction.source_type = "image"
    extraction.diagnostics.update(
        {
            "filename": filename,
            "model": model,
            "review_required": True,
            "screen_type": llm_result.screen_type,
            "visible_labels": visible_labels,
            "holdings_label_hits": holdings_label_hits,
        }
    )
    extraction.warnings.append("Screenshot extraction requires user review before syncing to the portfolio mirror.")
    return extraction
