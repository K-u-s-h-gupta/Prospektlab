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
    """Extract portfolio holdings from a screenshot image using OpenAI vision.

    Args:
        image_bytes: Image file bytes
        filename: Original filename

    Returns:
        PortfolioExtractionSchema with status='REVIEW_REQUIRED' (always gated for safety)

    Raises:
        PortfolioImageExtractionError: If extraction fails (API key missing, model error, etc.)
    """
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
    model = os.getenv("PORTFOLIO_VISION_MODEL", "gpt-4o-mini")

    prompt = (
        "Extract ONLY visible holdings from this Indian broker/DP portfolio screenshot. "
        "Supported brokers: Zerodha, Groww, Dhan, Shoonya, Angel, Motilal, Axis Direct, etc. "
        "Extract these fields per row: symbol (ticker), quantity, price/NAV, value, cost_basis, name. "
        "IMPORTANT number formatting: "
        "  - Indian lakhs notation: 1,23,456 = 123456; 2.5L = 250000; use exact numeric value in JSON. "
        "  - Parse '%' sign if present; store as ratio (e.g., '5%' = 0.05). "
        "  - If a value column shows '₹' or 'Rs', extract only the number. "
        "Do NOT infer or hallucinate missing grid values. If not visible, omit the field or use 0. "
        "Each position must include: symbol, quantity, market_value, confidence (0.0-1.0), raw_evidence (copy visible text). "
        "Use exchange 'NSE' for stocks unless screenshot shows BSE; 'AMFI' for mutual funds. "
        "Return JSON with status='REVIEW_REQUIRED', source_type='image', positions[], warnings[]. "
        "If unable to read any value clearly, set confidence=0.5 or lower for that row. "
        "If entire screen is unreadable, return empty positions[] with status='REVIEW_REQUIRED'."
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
            extraction = PortfolioExtractionSchema(
                status=llm_result.status,
                source_type=llm_result.source_type,
                broker_or_vendor=llm_result.broker_or_vendor,
                positions=llm_result.positions,
                warnings=llm_result.warnings,
                confidence=llm_result.confidence,
            )
        else:
            response = await client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            llm_result = PortfolioExtractionLLMResponse.model_validate(json.loads(content))
            extraction = PortfolioExtractionSchema(
                status=llm_result.status,
                source_type=llm_result.source_type,
                broker_or_vendor=llm_result.broker_or_vendor,
                positions=llm_result.positions,
                warnings=llm_result.warnings,
                confidence=llm_result.confidence,
            )
    except Exception as exc:
        logger.exception("OpenAI screenshot extraction failed")
        raise PortfolioImageExtractionError(f"Screenshot extraction failed: {exc}") from exc

    extraction.status = "REVIEW_REQUIRED"
    extraction.source_type = "image"
    extraction.diagnostics.update({"filename": filename, "model": model, "review_required": True})
    extraction.warnings.append("Screenshot extraction requires user review before syncing to the portfolio mirror.")
    return extraction
