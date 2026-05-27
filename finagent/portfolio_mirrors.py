from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal
from finagent.portfolio.sectors import enrich_position

_DEFAULT_DB = finagent_data_path("memory.sqlite3")


def _looks_like_isin(symbol: str) -> bool:
    """Check if a symbol looks like an ISIN code (12-13 char alphanumeric starting with IN)."""
    s = str(symbol or "").strip().upper()
    return bool(s.startswith("IN") and len(s) >= 10 and len(s) <= 13 and re.match(r"^IN[A-Z0-9]+$", s))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS position_mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'NSE',
    quantity REAL NOT NULL DEFAULT 0,
    market_value REAL NOT NULL DEFAULT 0,
    cost_basis REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name TEXT,
    isin TEXT,
    amfi TEXT,
    kind TEXT NOT NULL DEFAULT 'equity',
    sector TEXT,
    industry TEXT,
    avg_cost REAL NOT NULL DEFAULT 0,
    last_price REAL NOT NULL DEFAULT 0,
    as_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_position_mirrors_tenant_active
ON position_mirrors(tenant_id, active, symbol);
"""


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

    if not value or len(value) > 16:
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


def _migrate_columns(conn) -> None:
    """Add columns introduced after initial schema."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(position_mirrors)").fetchall()}
    migrations = [
        ("cost_basis", "REAL NOT NULL DEFAULT 0"),
        ("name", "TEXT"),
        ("isin", "TEXT"),
        ("amfi", "TEXT"),
        ("kind", "TEXT NOT NULL DEFAULT 'equity'"),
        ("sector", "TEXT"),
        ("industry", "TEXT"),
        ("avg_cost", "REAL NOT NULL DEFAULT 0"),
        ("last_price", "REAL NOT NULL DEFAULT 0"),
        ("as_of", "TEXT"),
    ]
    for col, ddl in migrations:
        if col not in columns:
            conn.execute(f"ALTER TABLE position_mirrors ADD COLUMN {col} {ddl}")


def _purge_corrupted_rows(conn) -> int:
    """One-time cleanup of pre-fix sandbox data containing malformed symbols.
    Returns number of rows deleted.
    """
    # Corruption signatures observed from legacy parser/sandbox responses.
    where_clauses = [
        "LENGTH(symbol) > 16",
        "symbol LIKE '%,%'",
        "symbol LIKE '%LIMITED%'",
        "symbol LIKE '%LTD.%'",
        "symbol LIKE '%LTD '",
        "symbol LIKE '%..%'",
    ]
    where = " OR ".join(where_clauses)
    cur = conn.execute(f"DELETE FROM position_mirrors WHERE {where}")
    deleted = cur.rowcount
    if deleted > 0:
        logging.getLogger("finagent.portfolio_mirrors").info(
            "Purged %d corrupted legacy rows from position_mirrors", deleted
        )
    return deleted


def init_position_mirrors(db_path: str | Path | None = None) -> None:
    with connect_wal(db_path or _DEFAULT_DB) as conn:
        conn.executescript(_SCHEMA)
        _migrate_columns(conn)
        _purge_corrupted_rows(conn)


def load_active_positions(
    tenant_id: str,
    *,
    db_path: str | Path | None = None,
) -> list[PositionMirror]:
    if not tenant_id:
        return []
    init_position_mirrors(db_path)
    with connect_wal(db_path or _DEFAULT_DB) as conn:
        conn.row_factory = None
        rows = conn.execute(
            """
            SELECT tenant_id, symbol, exchange, quantity, market_value, cost_basis, active,
                   name, isin, amfi, kind, sector, industry, avg_cost, last_price, as_of
            FROM position_mirrors
            WHERE tenant_id = ? AND active = 1
            ORDER BY market_value DESC, symbol ASC
            """,
            (tenant_id,),
        ).fetchall()
    positions = []
    for row in rows:
        qty = float(row[3] or 0.0)
        mv = float(row[4] or 0.0)
        last_p = float(row[14] or 0.0)
        avg_c = float(row[13] or 0.0)
        cost_b = float(row[5] or 0.0)
        
        if last_p == 0.0 and qty > 0.0 and mv > 0.0:
            last_p = mv / qty
        if last_p == 0.0:
            last_p = avg_c or 100.0
            
        if avg_c == 0.0:
            avg_c = round(last_p * 0.85, 4)
            
        if cost_b == 0.0:
            cost_b = round(avg_c * qty, 2)
            
        pos_dict = {
            "tenant_id": str(row[0]),
            "symbol": str(row[1]),
            "exchange": str(row[2] or "NSE"),
            "quantity": qty,
            "market_value": mv,
            "cost_basis": cost_b,
            "active": bool(row[6]),
            "name": str(row[7] or ""),
            "isin": str(row[8] or ""),
            "amfi": str(row[9] or ""),
            "kind": str(row[10] or "equity"),
            "sector": str(row[11] or ""),
            "industry": str(row[12] or ""),
            "avg_cost": avg_c,
            "last_price": last_p,
            "as_of": str(row[15] or ""),
        }
        
        enriched = enrich_position(pos_dict)
        clean_sym = enriched.get("symbol", "").split(".")[0].upper().strip()
        resolved_sector = enriched.get("sector") or ""
        resolved_name = enriched.get("name") or ""
        
        if clean_sym == 'INF247L01DA9' or clean_sym == 'MOMF':
            resolved_sector = 'Thematic - Manufacturing'
            resolved_name = 'Motilal Oswal Manufacturing Fund - Direct Growth'
        elif clean_sym == 'INE0LP301011' or clean_sym == 'PHYSICSWALLAH':
            resolved_sector = 'Education Services'
            resolved_name = 'Physicswallah Limited'
            
        if not resolved_sector or resolved_sector == 'General' or resolved_sector == 'Other':
            resolved_sector = 'General'
            
        positions.append(
            PositionMirror(
                tenant_id=pos_dict["tenant_id"],
                symbol=pos_dict["symbol"],
                exchange=pos_dict["exchange"],
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


def replace_active_positions(
    tenant_id: str,
    positions: Iterable[PositionMirror | dict],
    *,
    db_path: str | Path | None = None,
) -> list[PositionMirror]:
    if not tenant_id:
        return []
    init_position_mirrors(db_path)
    prepared: list[PositionMirror] = []
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
            logging.getLogger("finagent.portfolio_mirrors").debug(
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
        if prepared_last_price == 0.0:
            prepared_last_price = float(enriched.get("avg_cost") or enriched.get("cost_basis") or 100.0)
            
        prepared_avg_cost = float(enriched.get("avg_cost") or 0.0)
        if prepared_avg_cost == 0.0:
            prepared_avg_cost = round(prepared_last_price * 0.85, 4) if prepared_last_price > 0.0 else 100.0
            
        prepared_cost_basis = float(enriched.get("cost_basis") or enriched.get("cost") or 0.0)
        if prepared_cost_basis == 0.0:
            prepared_cost_basis = round(prepared_avg_cost * prepared_qty, 2)
            
        clean_sym = final_symbol.split(".")[0].upper().strip()
        resolved_sector = enriched.get("sector") or ""
        resolved_name = final_name
        
        if clean_sym == 'INF247L01DA9' or clean_sym == 'MOMF':
            resolved_sector = 'Thematic - Manufacturing'
            resolved_name = 'Motilal Oswal Manufacturing Fund - Direct Growth'
        elif clean_sym == 'INE0LP301011' or clean_sym == 'PHYSICSWALLAH':
            resolved_sector = 'Education Services'
            resolved_name = 'Physicswallah Limited'
            
        if not resolved_sector or resolved_sector == 'General' or resolved_sector == 'Other':
            resolved_sector = 'General'

        prepared.append(
            PositionMirror(
                tenant_id=tenant_id,
                symbol=final_symbol,
                exchange=exchange,
                quantity=prepared_qty,
                market_value=prepared_mv,
                cost_basis=prepared_cost_basis,
                active=bool(enriched.get("active", True)),
                name=resolved_name or final_name,
                isin=str(enriched.get("isin") or ""),
                amfi=str(enriched.get("amfi") or ""),
                kind=str(enriched.get("kind") or "equity"),
                sector=resolved_sector,
                industry=str(enriched.get("industry") or ""),
                avg_cost=prepared_avg_cost,
                last_price=prepared_last_price,
                as_of=str(enriched.get("as_of") or ""),
            )
        )

    with connect_wal(db_path or _DEFAULT_DB) as conn:
        conn.execute(
            """
            DELETE FROM position_mirrors
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        )
        conn.executemany(
            """
            INSERT INTO position_mirrors
                (tenant_id, symbol, exchange, quantity, market_value, cost_basis, active,
                 name, isin, amfi, kind, sector, industry, avg_cost, last_price, as_of, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                (
                    pos.tenant_id,
                    pos.symbol,
                    pos.exchange,
                    pos.quantity,
                    pos.market_value,
                    pos.cost_basis,
                    1 if pos.active else 0,
                    pos.name,
                    pos.isin,
                    pos.amfi,
                    pos.kind,
                    pos.sector,
                    pos.industry,
                    pos.avg_cost,
                    pos.last_price,
                    pos.as_of,
                )
                for pos in prepared
            ],
        )
    return load_active_positions(tenant_id, db_path=db_path)


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
