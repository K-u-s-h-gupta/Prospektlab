from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Iterable

from finagent.paths import finagent_data_path
from finagent.portfolio.sectors import enrich_position
from finagent.storage.supabase_store import get_portfolio_store

logger = logging.getLogger("finagent.portfolio_mirrors")


def _looks_like_isin(symbol: str) -> bool:
    """Check if a symbol looks like an ISIN code (12-13 char alphanumeric starting with IN)."""
    s = str(symbol or "").strip().upper()
    return bool(s.startswith("IN") and len(s) >= 10 and len(s) <= 13 and re.match(r"^IN[A-Z0-9]+$", s))


@dataclass(frozen=True)
class PositionMirror:
    tenant_id: str
    symbol: str
    exchange: str
    quantity: float
    market_value: float
    cost_basis: float = 0.0
    active: bool = True
    name: str = ""
    isin: str = ""
    amfi: str = ""
    kind: str = "equity"
    sector: str = ""
    industry: str = ""
    avg_cost: float = 0.0
    last_price: float = 0.0
    as_of: str = ""

    @property
    def normalized_symbol(self) -> str:
        return self.symbol.strip().upper().removesuffix(".NS").removesuffix(".BO")

    @property
    def exchange_symbol(self) -> str:
        base = self.normalized_symbol
        exchange = (self.exchange or "NSE").strip().upper()
        if not base:
            return ""
        if exchange == "AMFI":
            return base
        if exchange in {"BSE", "BO", ".BO"}:
            return f"{base}.BO"
        return f"{base}.NS"


def normalize_exchange(exchange: str | None) -> str:
    value = (exchange or "NSE").strip().upper()
    if value in {"AMFI", "MF", "MUTUALFUND", "MUTUAL FUND"}:
        return "AMFI"
    if value in {"BSE", "BOMBAY", "BO", ".BO"}:
        return "BSE"
    return "NSE"


def normalize_symbol(symbol: str, exchange: str | None = None) -> str:
    value = (symbol or "").strip().upper()
    value = value.replace(" ", "").replace("_EQ", "")
    exchange_norm = normalize_exchange(exchange)
    if exchange_norm == "AMFI":
        value = re.sub(r"[^A-Z0-9]", "", value)
        return value[:32]

    # Strip common corporate suffixes that appeared in old sandbox data
    for suffix in ("LIMITED", "LTD.", "LTD"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    value = value.rstrip(",.")  # trailing junk

    if not value:
        return ""
    # Non-traded asset kinds (physical gold, SGB) may have long symbols or ISINs
    if exchange_norm in {"AMFI", "MF"}:
        if len(value) > 32:
            return ""
    elif len(value) > 16:
        return ""

    # Reject anything still containing commas or double-dots (corruption markers)
    if "," in value or ".." in value:
        return ""

    if value.endswith(".NS") or value.endswith(".BO"):
        return value
    suffix = ".BO" if exchange_norm == "BSE" else ".NS"
    return f"{value.removesuffix('.NSE').removesuffix('.BSE')}{suffix}"


def clean_position_name(name: str) -> str:
    if not name:
        return ""
    # Replace newlines, tabs, carriage returns with spaces
    name = re.sub(r"[\r\n\t]+", " ", name)
    # Remove Devanagari (Hindi) characters (range \u0900-\u097F)
    name = re.sub(r"[\u0900-\u097F]+", " ", name)
    # Replace multiple spaces with a single space
    name = re.sub(r"\s+", " ", name)
    name = name.strip()
    # Strip trailing ISINs or codes from the name if merged
    name = re.sub(r"\s+IN[A-Z0-9]{10}\d\b", "", name, flags=re.IGNORECASE)
    # Strip residual header noise
    for junk in ("profit/loss", "loss(%)", "dividend", "valuation", "value"):
        name = re.sub(rf"\b{re.escape(junk)}\b", "", name, flags=re.IGNORECASE)
    # Re-normalize spacing
    name = re.sub(r"\s+", " ", name).strip()
    return name


async def load_active_positions(
    tenant_id: str,
) -> list[PositionMirror]:
    if not tenant_id:
        raise ValueError("tenant_id is required for portfolio operations")
    store = get_portfolio_store()
    rows = await store.load_active_positions(tenant_id)
    return _rows_to_position_mirrors(rows)


def _rows_to_position_mirrors(rows: Iterable[dict]) -> list[PositionMirror]:
    positions = []
    for row in rows:
        qty = float(row.get("quantity") or 0.0)
        mv = float(row.get("market_value") or 0.0)
        last_p = float(row.get("last_price") or 0.0)
        avg_c = float(row.get("avg_cost") or 0.0)
        cost_b = float(row.get("cost_basis") or 0.0)
        
        if last_p == 0.0 and qty > 0.0 and mv > 0.0:
            last_p = mv / qty
            
        if avg_c == 0.0 and cost_b > 0.0 and qty > 0.0:
            avg_c = round(cost_b / qty, 4)
        elif avg_c == 0.0 and last_p > 0.0:
            avg_c = last_p
            
        if cost_b == 0.0 and avg_c > 0.0:
            cost_b = round(avg_c * qty, 2)
            
        pos_dict = {
            "tenant_id": str(row.get("tenant_id")),
            "symbol": str(row.get("symbol")),
            "exchange": str(row.get("exchange") or "NSE"),
            "quantity": qty,
            "market_value": mv,
            "cost_basis": cost_b,
            "active": bool(row.get("active")),
            "name": str(row.get("name") or ""),
            "isin": str(row.get("isin") or ""),
            "amfi": str(row.get("amfi") or ""),
            "kind": str(row.get("kind") or "equity"),
            "sector": str(row.get("sector") or ""),
            "industry": str(row.get("industry") or ""),
            "avg_cost": avg_c,
            "last_price": last_p,
            "as_of": str(row.get("as_of") or ""),
        }
        
        enriched = enrich_position(pos_dict)
        resolved_sector = enriched.get("sector") or ""
        resolved_name = enriched.get("name") or ""
            
        if not resolved_sector or resolved_sector.strip().lower() in {"general", "other", "unknown", "n/a", "na"}:
            resolved_sector = 'General'
            
        positions.append(
            PositionMirror(
                tenant_id=pos_dict["tenant_id"],
                symbol=enriched.get("symbol") or pos_dict["symbol"],
                exchange=enriched.get("exchange") or pos_dict["exchange"],
                quantity=pos_dict["quantity"],
                market_value=pos_dict["market_value"],
                cost_basis=pos_dict["cost_basis"],
                active=pos_dict["active"],
                name=resolved_name or pos_dict["name"],
                isin=pos_dict["isin"],
                amfi=pos_dict["amfi"],
                kind=pos_dict["kind"],
                sector=resolved_sector,
                industry=enriched.get("industry") or pos_dict["industry"],
                avg_cost=pos_dict["avg_cost"],
                last_price=pos_dict["last_price"],
                as_of=pos_dict["as_of"],
            )
        )
    return positions


async def replace_active_positions(
    tenant_id: str,
    positions: Iterable[PositionMirror | dict],
) -> list[PositionMirror]:
    if not tenant_id:
        raise ValueError("tenant_id is required for portfolio operations")
    prepared: list[dict] = []
    for item in positions:
        raw = item if isinstance(item, dict) else asdict(item)
        exchange = normalize_exchange(raw.get("exchange"))
        symbol = normalize_symbol(str(raw.get("symbol") or raw.get("isin") or raw.get("amfi") or ""), exchange)
        if not symbol:
            continue
        # Reject only rows with neither identity nor numeric holdings evidence.
        name = clean_position_name(str(raw.get("name") or "").strip())
        cost = float(raw.get("cost_basis") or raw.get("cost") or 0.0)
        isin = str(raw.get("isin") or "").strip()
        quantity = float(raw.get("quantity") or 0.0)
        market_value = float(raw.get("market_value") or 0.0)
        if not name and not isin and quantity <= 0 and market_value <= 0:
            logger.debug(
                "Skipping position without identity/numeric evidence for symbol=%s", symbol
            )
            continue

        # Prepare a cleaned dict for enrichment
        raw_copy = dict(raw)
        raw_copy["name"] = name
        raw_copy["symbol"] = symbol
        raw_copy["isin"] = isin

        # Enrich with sector/name from bundled + cache
        enriched = enrich_position(raw_copy)
        final_name = clean_position_name(enriched.get("name") or name)
        
        # Prefer enriched symbol; if still an ISIN, try live ISIN resolution
        enriched_symbol = enriched.get("symbol") or symbol
        if enriched_symbol and _looks_like_isin(enriched_symbol):
            try:
                from finagent.ingestion.isin_resolver import resolve_isin
                resolution = resolve_isin(enriched_symbol, kind_hint=raw_copy.get("kind", "equity"))
                if resolution and resolution.get("symbol"):
                    enriched_symbol = resolution["symbol"]
            except Exception:
                pass  # Keep original if resolution fails
        
        final_symbol = normalize_symbol(enriched_symbol, exchange)

        prepared_qty = float(enriched.get("quantity") or 0.0)
        prepared_mv = float(enriched.get("market_value") or 0.0)
        prepared_last_price = float(enriched.get("last_price") or 0.0)
        if prepared_last_price == 0.0 and prepared_qty > 0.0 and prepared_mv > 0.0:
            prepared_last_price = prepared_mv / prepared_qty
        prepared_avg_cost = float(enriched.get("avg_cost") or 0.0)
        if prepared_last_price == 0.0 and prepared_avg_cost > 0.0:
            prepared_last_price = prepared_avg_cost
            
        prepared_cost_basis = float(enriched.get("cost_basis") or enriched.get("cost") or 0.0)
        if prepared_avg_cost == 0.0 and prepared_cost_basis > 0.0 and prepared_qty > 0.0:
            prepared_avg_cost = round(prepared_cost_basis / prepared_qty, 4)
        if prepared_cost_basis == 0.0 and prepared_avg_cost > 0.0:
            prepared_cost_basis = round(prepared_avg_cost * prepared_qty, 2)
            
        resolved_sector = enriched.get("sector") or ""
        resolved_name = final_name
            
        if not resolved_sector or resolved_sector.strip().lower() in {"general", "other", "unknown", "n/a", "na"}:
            resolved_sector = 'General'

        prepared.append({
            "tenant_id": tenant_id,
            "symbol": final_symbol,
            "exchange": exchange,
            "quantity": prepared_qty,
            "market_value": prepared_mv,
            "cost_basis": prepared_cost_basis,
            "active": bool(enriched.get("active", True)),
            "name": resolved_name or final_name,
            "isin": str(enriched.get("isin") or ""),
            "amfi": str(enriched.get("amfi") or ""),
            "kind": str(enriched.get("kind") or "equity"),
            "sector": resolved_sector,
            "industry": str(enriched.get("industry") or ""),
            "avg_cost": prepared_avg_cost,
            "last_price": prepared_last_price,
            "as_of": str(enriched.get("as_of") or ""),
        })

    if not prepared:
        logger.warning("No valid portfolio positions remained after normalization for tenant %s", tenant_id)
        return []

    store = get_portfolio_store()
    try:
        stored_rows = await store.replace_active_positions(tenant_id, prepared)
    except Exception as exc:  # noqa: BLE001 - mirror persistence is best-effort
        logger.warning("Portfolio mirror write failed for tenant %s; falling back to in-memory holdings: %s", tenant_id, exc)
        stored_rows = []
    if stored_rows:
        return _rows_to_position_mirrors(stored_rows)
    # Mirror backend (Supabase) unreachable or returned nothing. The frontend's
    # localStorage is the source of truth in open-access mode, so still return the
    # holdings we just prepared instead of failing the whole upload with a 500/503.
    try:
        loaded = await load_active_positions(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Portfolio mirror read-back failed for tenant %s; using prepared rows: %s", tenant_id, exc)
        loaded = []
    if loaded:
        return loaded
    return _rows_to_position_mirrors(prepared)


async def delete_positions(tenant_id: str) -> int:
    if not tenant_id:
        raise ValueError("tenant_id is required for portfolio operations")
    store = get_portfolio_store()
    return await store.delete_positions(tenant_id)


async def clear_all_positions() -> int:
    """Admin reset: delete every portfolio mirror row for every tenant."""
    store = get_portfolio_store()
    return await store.clear_all()


def portfolio_weights(positions: Iterable[PositionMirror]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for pos in positions:
        symbol = pos.exchange_symbol
        if symbol and pos.market_value > 0:
            totals[symbol] = totals.get(symbol, 0.0) + pos.market_value
    total_value = sum(totals.values())
    if total_value <= 0:
        return {}
    return {symbol: value / total_value for symbol, value in totals.items()}


def sector_breakdown(positions: Iterable[PositionMirror]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for pos in positions:
        sector = (pos.sector or "Unknown").strip()
        if sector and pos.market_value > 0:
            totals[sector] = totals.get(sector, 0.0) + pos.market_value
    total_value = sum(totals.values())
    if total_value <= 0:
        return {}
    return {sector: value / total_value for sector, value in totals.items()}


def kind_breakdown(positions: Iterable[PositionMirror]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for pos in positions:
        kind = (pos.kind or "equity").strip()
        if pos.market_value > 0:
            totals[kind] = totals.get(kind, 0.0) + pos.market_value
    total_value = sum(totals.values())
    if total_value <= 0:
        return {}
    return {k: v / total_value for k, v in totals.items()}


def summarize_positions(positions: Iterable[PositionMirror]) -> dict:
    items = list(positions)
    weights = portfolio_weights(items)
    sectors = sector_breakdown(items)
    kinds = kind_breakdown(items)
    total_value = sum(pos.market_value for pos in items if pos.market_value > 0)
    total_cost = sum(pos.cost_basis for pos in items if pos.cost_basis > 0)
    status = "MIRROR_SYNCHRONIZED" if items else "MIRROR_EMPTY"
    return {
        "status": status,
        "sync_status": status,
        "count": len(items),
        "total_market_value": total_value,
        "total_cost_basis": total_cost,
        "weights": weights,
        "hhi": sum(weight * weight for weight in weights.values()),
        "sector_breakdown": sectors,
        "kind_breakdown": kinds,
        "positions": [
            {
                "symbol": pos.exchange_symbol,
                "name": pos.name,
                "exchange": pos.exchange,
                "quantity": pos.quantity,
                "market_value": pos.market_value,
                "cost_basis": pos.cost_basis,
                "unrealized_pnl": pos.market_value - pos.cost_basis if pos.cost_basis else None,
                "active": pos.active,
                "weight": weights.get(pos.exchange_symbol, 0.0),
                "kind": pos.kind,
                "sector": pos.sector,
                "industry": pos.industry,
                "isin": pos.isin,
                "amfi": pos.amfi,
                "avg_cost": pos.avg_cost,
                "last_price": pos.last_price,
                "as_of": pos.as_of,
            }
            for pos in items
        ],
    }
