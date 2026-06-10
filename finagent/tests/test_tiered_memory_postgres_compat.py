from __future__ import annotations

from pathlib import Path


def _backend():
    from finagent.memory.tiered_store import MemoryConfig, PostgresTieredBackend

    return PostgresTieredBackend(
        MemoryConfig(
            backend="prospekt_tiered",
            database_url="postgres://memory",
            vector_dim=1536,
            embeddings_enabled=False,
            timeout_s=8.0,
            use_in_memory=False,
        )
    )


def _record():
    return {
        "user_email": "memory@example.com",
        "tenant_id": "",
        "target_key": "tcs",
        "cin": None,
        "isin": None,
        "symbol": "TCS",
        "kind": "financial",
        "body": "Revenue grew year over year.",
        "body_hash": "abc123",
        "confidence": "HIGH",
        "source_url": "https://example.com/fact",
        "session_id": "sess-1",
        "session_key": "sess-1",
        "metadata_json": {"record_type": "fact"},
        "legacy_source": None,
        "legacy_id": None,
        "created_at": 1710000000.0,
        "expires_at": 1710003600.0,
    }


def test_recall_query_uses_datetime_fallback_when_expiry_epoch_is_missing():
    from finagent.memory.tiered_store import RECALL_MEMORY_REQUIRED_COLUMNS, RecallMemorySchemaCapabilities

    backend = _backend()
    caps = RecallMemorySchemaCapabilities(
        columns=frozenset(RECALL_MEMORY_REQUIRED_COLUMNS - {"expires_at_epoch"})
    )

    sql, params = backend._build_recall_query_statement(
        user_email="memory@example.com",
        target_key="tcs",
        kind="financial",
        limit=10,
        caps=caps,
    )

    assert "extract(epoch from expires_at) as expires_at" in sql
    assert "(expires_at is null or expires_at > now())" in sql
    assert "created_at_epoch as created_at" in sql
    assert params[-1] == 10


def test_recall_query_uses_created_at_fallback_when_created_epoch_is_missing():
    from finagent.memory.tiered_store import RECALL_MEMORY_REQUIRED_COLUMNS, RecallMemorySchemaCapabilities

    backend = _backend()
    caps = RecallMemorySchemaCapabilities(
        columns=frozenset(RECALL_MEMORY_REQUIRED_COLUMNS - {"created_at_epoch"})
    )

    sql, _params = backend._build_recall_query_statement(
        user_email="memory@example.com",
        target_key=None,
        kind=None,
        limit=5,
        caps=caps,
    )

    assert "extract(epoch from created_at) as created_at" in sql
    assert "order by extract(epoch from created_at) desc, id desc" in sql


def test_recall_insert_supports_full_and_legacy_column_shapes():
    from finagent.memory.tiered_store import RECALL_MEMORY_REQUIRED_COLUMNS, RecallMemorySchemaCapabilities

    backend = _backend()
    record = _record()

    full_caps = RecallMemorySchemaCapabilities(columns=frozenset(RECALL_MEMORY_REQUIRED_COLUMNS))
    legacy_caps = RecallMemorySchemaCapabilities(
        columns=frozenset(RECALL_MEMORY_REQUIRED_COLUMNS - {"expires_at", "expires_at_epoch"})
    )

    full_sql, full_params = backend._build_recall_insert_statement(record, full_caps)
    legacy_sql, legacy_params = backend._build_recall_insert_statement(record, legacy_caps)

    assert "expires_at_epoch" in full_sql
    assert "expires_at_epoch" not in legacy_sql
    assert "expires_at," not in legacy_sql
    assert len(full_params) == len(legacy_params) + 2


def test_memory_runtime_bootstrap_executes_idempotent_expiry_patch(monkeypatch):
    import finagent.memory.tiered_store as tiered_store

    executed: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append(sql)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    tiered_store._MEMORY_BOOTSTRAPPED_URLS.clear()
    monkeypatch.setattr(tiered_store, "_connect_postgres", lambda *args, **kwargs: FakeConn())
    monkeypatch.setattr(
        tiered_store,
        "_memory_bootstrap_sql",
        lambda: "alter table if exists public.recall_memories add column if not exists expires_at timestamptz;\n"
        "alter table if exists public.recall_memories add column if not exists expires_at_epoch double precision;",
    )

    assert tiered_store.ensure_memory_runtime_tables("postgres://memory")
    assert executed
    assert "add column if not exists expires_at timestamptz" in executed[0]
    assert "add column if not exists expires_at_epoch double precision" in executed[0]


def test_bootstrap_contract_contains_runtime_required_recall_columns():
    from finagent.memory.tiered_store import RECALL_MEMORY_REQUIRED_COLUMNS

    sql = (Path(__file__).resolve().parents[2] / "deployment" / "prospekt_memory_bootstrap.sql").read_text(encoding="utf-8")

    for column in ("created_at", "created_at_epoch", "expires_at", "expires_at_epoch"):
        assert column in RECALL_MEMORY_REQUIRED_COLUMNS
        assert column in sql
