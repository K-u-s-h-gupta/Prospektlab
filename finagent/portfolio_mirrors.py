from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal
from finagent.portfolio.sectors import enrich_position

_DEFAULT_DB = finagent_data_path("memory.sqlite3")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS position_mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'NSE',
    quantity REAL NOT NULL DEFAULT 0,
    market_value REAL NOT NULL DEFAULT 0,
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
        if exchange in {"BSE", "BO", ".BO"}:
            return f"{base}.BO"
        return f"{base}.NS"


def normalize_exchange(exchange: str | None) -> str:
    value = (exchange or "NSE").strip().upper()
    if value in {"BSE", "BOMBAY", "BO", ".BO"}:
        return "BSE"
    return "NSE"


def normalize_symbol(symbol: str, exchange: str | None = None) -> str:
    value = (symbol or "").strip().upper()
    value = value.replace(" ", "").replace("_EQ", "")

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
    suffix = ".BO" if normalize_exchange(exchange) == "BSE" else ".NS"
    return f"{value.removesuffix('.NSE').removesuffix('.BSE')}{suffix}"


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
    # Corruption signatures observed from old CASParser sandbox responses
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


def _purge_stale_rows(conn) -> int:
    """Aggressive purge of stale rows (name=NULL OR cost_basis=0 AND isin IS NULL).
    Uses _meta_state version table to run only once per version.
    Returns number of rows deleted.
    """
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _meta_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
    except Exception:
        pass

    row = conn.execute("SELECT value FROM _meta_state WHERE key = 'purge_v'").fetchone()
    current_v = int(row[0]) if row else 0
    target_v = 2  # bump when purge criteria change

    if current_v >= target_v:
        return 0

    cur = conn.execute(
        """
        DELETE FROM position_mirrors
        WHERE name IS NULL
           OR (cost_basis = 0 AND isin IS NULL)
        """
    )
    deleted = cur.rowcount
    conn.execute(
        "INSERT INTO _meta_state(key, value) VALUES ('purge_v', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(target_v),),
    )
    if deleted > 0:
        logging.getLogger("finagent.portfolio_mirrors").info(
            "Purged %d stale rows (name=NULL or cost_basis=0+isin=NULL) from position_mirrors", deleted
        )
    return deleted


def init_position_mirrors(db_path: str | Path | None = None) -> None:
    with connect_wal(db_path or _DEFAULT_DB) as conn:
        conn.executescript(_SCHEMA)
        _migrate_columns(conn)
        _purge_corrupted_rows(conn)
        _purge_stale_rows(conn)


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
    return [
        PositionMirror(
            tenant_id=str(row[0]),
            symbol=str(row[1]),
            exchange=str(row[2] or "NSE"),
            quantity=float(row[3] or 0.0),
            market_value=float(row[4] or 0.0),
            cost_basis=float(row[5] or 0.0),
            active=bool(row[6]),
            name=str(row[7] or ""),
            isin=str(row[8] or ""),
            amfi=str(row[9] or ""),
            kind=str(row[10] or "equity"),
            sector=str(row[11] or ""),
            industry=str(row[12] or ""),
            avg_cost=float(row[13] or 0.0),
            last_price=float(row[14] or 0.0),
            as_of=str(row[15] or ""),
        )
        for row in rows
    ]


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
        raw = item if isinstance(item, dict) else item.__dict__
        exchange = normalize_exchange(raw.get("exchange"))
        symbol = normalize_symbol(str(raw.get("symbol") or ""), exchange)
        if not symbol:
            continue
        # Reject sandbox-like inserts (empty name, zero cost, no ISIN)
        name = str(raw.get("name") or "").strip()
        cost = float(raw.get("cost_basis") or raw.get("cost") or 0.0)
        isin = str(raw.get("isin") or "").strip()
        if not name and cost == 0.0 and not isin:
            logging.getLogger("finagent.portfolio_mirrors").debug(
                "Skipping sandbox-like insert for symbol=%s", symbol
            )
            continue
        # Enrich with sector/name from bundled + cache
        enriched = enrich_position(raw)
        prepared.append(
            PositionMirror(
                tenant_id=tenant_id,
                symbol=symbol,
                exchange=exchange,
                quantity=float(enriched.get("quantity") or 0.0),
                market_value=float(enriched.get("market_value") or 0.0),
                cost_basis=float(enriched.get("cost_basis") or enriched.get("cost") or 0.0),
                active=bool(enriched.get("active", True)),
                name=str(enriched.get("name") or ""),
                isin=str(enriched.get("isin") or ""),
                amfi=str(enriched.get("amfi") or ""),
                kind=str(enriched.get("kind") or "equity"),
                sector=str(enriched.get("sector") or ""),
                industry=str(enriched.get("industry") or ""),
                avg_cost=float(enriched.get("avg_cost") or 0.0),
                last_price=float(enriched.get("last_price") or 0.0),
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
