from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AssetKind = Literal["equity", "mf", "etf", "bond", "cash", "other"]
ExtractionStatus = Literal[
    "MIRROR_SYNCHRONIZED",
    "REVIEW_REQUIRED",
    "MIRROR_EMPTY",
    "INGESTION_FAILED",
]


class StrictBaseModel(BaseModel):
    """Base for models that must produce OpenAI-structured-output compatible schemas.

    OpenAI strict mode requires every object in the JSON schema to declare
    "additionalProperties": false. Inheriting from this ensures the generated
    schema satisfies that constraint.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"additionalProperties": False},
    )


class PortfolioPositionSchema(StrictBaseModel):
    symbol: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=180)
    isin: str = Field(default="", max_length=16)
    amfi: str = Field(default="", max_length=24)
    exchange: str = Field(default="NSE", max_length=12)
    kind: AssetKind = "equity"
    quantity: float = Field(default=0.0, ge=0)
    market_value: float = Field(default=0.0, ge=0)
    cost_basis: float = Field(default=0.0, ge=0)
    avg_cost: float = Field(default=0.0, ge=0)
    last_price: float = Field(default=0.0, ge=0)
    as_of: str = Field(default="", max_length=40)
    confidence: float = Field(default=0.0, ge=0, le=1)
    raw_evidence: str = Field(default="", max_length=500)

    @field_validator("symbol", "isin", "amfi", "exchange", mode="before")
    @classmethod
    def _upper_compact(cls, value: object) -> str:
        return str(value or "").strip().upper()

    @field_validator("name", "as_of", "raw_evidence", mode="before")
    @classmethod
    def _clean_text(cls, value: object) -> str:
        return " ".join(str(value or "").split())


class PortfolioExtractionSchema(BaseModel):
    """Primary Python-side extraction result.

    Contains flexible dict bags (diagnostics, investor) for runtime use by
    document pipelines and error reporting. Never passed directly to OpenAI
    structured outputs — use PortfolioExtractionLLMResponse for that.
    """

    model_config = ConfigDict(extra="ignore")

    status: ExtractionStatus = "REVIEW_REQUIRED"
    source_type: Literal["pdf", "csv", "xlsx", "image", "unknown"] = "unknown"
    broker_or_vendor: str = Field(default="", max_length=80)
    investor: dict[str, str | None] = Field(default_factory=dict)
    positions: list[PortfolioPositionSchema] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    diagnostics: dict = Field(default_factory=dict)

    @property
    def has_syncable_positions(self) -> bool:
        return any((p.symbol or p.isin or p.name) and (p.quantity > 0 or p.market_value > 0) for p in self.positions)


class PortfolioExtractionLLMResponse(StrictBaseModel):
    """Strict subset schema intended exclusively for OpenAI structured outputs.

    This model is safe to pass as `response_format=` to the OpenAI beta parse
    endpoint. It deliberately excludes the dynamic dict fields (diagnostics,
    investor) — those are populated in Python code after the LLM call.
    """

    status: ExtractionStatus = "REVIEW_REQUIRED"
    source_type: Literal["pdf", "csv", "xlsx", "image", "unknown"] = "unknown"
    broker_or_vendor: str = Field(default="", max_length=80)
    positions: list[PortfolioPositionSchema] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class PortfolioExtractionReview(StrictBaseModel):
    review_id: str
    extraction: PortfolioExtractionSchema


class PortfolioExtractionConfirmRequest(StrictBaseModel):
    review_id: str | None = None
    positions: list[PortfolioPositionSchema] = Field(default_factory=list, max_length=1000)
    source_type: str = "review"


def ensure_openai_strict_schema(model: type[BaseModel]) -> dict:
    """Return the JSON schema for a model and assert it is safe for OpenAI strict mode.

    Raises AssertionError if any object property lacks "additionalProperties": false.
    Use this in tests or at import time to prevent regressions.
    """
    schema = model.model_json_schema()

    def _check(obj: dict) -> None:
        if not isinstance(obj, dict):
            return
        if obj.get("type") == "object":
            addl = obj.get("additionalProperties")
            if addl is not False:
                path = obj.get("title") or "<anonymous object>"
                raise AssertionError(f"OpenAI strict schema violation in {path}: additionalProperties={addl!r}")
        for v in obj.values():
            if isinstance(v, dict):
                _check(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        _check(item)

    _check(schema)
    return schema

