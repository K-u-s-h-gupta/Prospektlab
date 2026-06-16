from __future__ import annotations

from contextlib import contextmanager


def setup_function(function):
    import finagent.ikg.pipeline.run_store as run_store

    run_store._RUNTIME_CONTROL_CACHE.clear()
    run_store._RUNTIME_CONTROL_BACKOFF_UNTIL.clear()
    run_store._RUNTIME_CONTROL_LAST_ERROR.clear()


def test_runtime_control_cache_isolated_by_database_url(monkeypatch):
    import finagent.ikg.pipeline.run_store as run_store

    calls: list[str] = []

    class FakeCursor:
        def __init__(self, enabled: bool):
            self.enabled = enabled

        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return (self.enabled,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self, enabled: bool):
            self.enabled = enabled

        def cursor(self):
            return FakeCursor(self.enabled)

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_connect_postgres(db_url: str, *, connect_timeout: int):
        calls.append(db_url)
        enabled = db_url.endswith("db-a")
        return FakeConnection(enabled)

    monkeypatch.setattr(run_store, "connect_postgres", fake_connect_postgres)

    assert run_store.is_runtime_control_enabled("pipeline_enabled", database_url="postgres://db-a") is True
    assert run_store.is_runtime_control_enabled("pipeline_enabled", database_url="postgres://db-b") is False
    assert run_store.is_runtime_control_enabled("pipeline_enabled", database_url="postgres://db-a") is True

    assert calls == ["postgres://db-a", "postgres://db-b"]


def test_runtime_control_backoff_does_not_cross_database_urls(monkeypatch):
    import finagent.ikg.pipeline.run_store as run_store

    calls: list[str] = []

    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return (True,)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_connect_postgres(db_url: str, *, connect_timeout: int):
        calls.append(db_url)
        if db_url.endswith("db-a"):
            raise TimeoutError("connection timeout expired")
        return FakeConnection()

    monkeypatch.setattr(run_store, "connect_postgres", fake_connect_postgres)

    assert run_store.is_runtime_control_enabled("pipeline_enabled", database_url="postgres://db-a") is True
    assert run_store.is_runtime_control_enabled("pipeline_enabled", database_url="postgres://db-b") is True

    assert calls == ["postgres://db-a", "postgres://db-b"]
