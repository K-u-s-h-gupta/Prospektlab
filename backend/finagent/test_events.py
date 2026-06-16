from finagent.events import SessionBus


class _FakeEventLog:
    def __init__(self) -> None:
        self.contents = ""

    def is_file(self) -> bool:
        return bool(self.contents)

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.contents

    def unlink(self, *, missing_ok: bool = False) -> None:
        self.contents = ""

    def write_text(self, text: str, encoding: str = "utf-8") -> None:
        self.contents = text


class _LockedClosedMarker:
    def __init__(self) -> None:
        self.exists = False

    def unlink(self, *, missing_ok: bool = False) -> None:
        raise OSError("simulated OneDrive lock")

    def write_text(self, text: str, encoding: str = "utf-8") -> None:
        self.exists = True

    def is_file(self) -> bool:
        return self.exists


def test_open_reset_starts_fresh_run_without_replaying_old_memo():
    bus = SessionBus()
    event_log = _FakeEventLog()
    closed_marker = _LockedClosedMarker()
    bus._session_dir = lambda session_id: None
    bus._events_path = lambda session_id: event_log
    bus._closed_path = lambda session_id: closed_marker
    async def _noop_append_event_file(session_id, event):
        pass
    bus._append_event_file = _noop_append_event_file

    bus.open("same-session")
    bus.emit("same-session", "memo", preview="old comprehensive memo")
    bus.close("same-session")

    assert bus.is_closed("same-session") is True
    assert [event.type for _, event in bus.history("same-session")] == ["memo"]

    bus.open("same-session", reset=True)

    assert bus.is_closed("same-session") is False
    assert bus.history("same-session") == []

    bus.emit("same-session", "session_started", objective="provide me its latest news")
    history = bus.history("same-session")
    assert len(history) == 1
    assert history[0][0] == 0
    assert history[0][1].type == "session_started"


def test_session_bus_remove_with_queue_matching():
    import asyncio
    bus = SessionBus()
    event_log = _FakeEventLog()
    bus._session_dir = lambda session_id: None
    bus._events_path = lambda session_id: event_log
    bus._closed_path = lambda session_id: None
    q1 = bus.open("test-session")
    q2 = bus.open("test-session")
    
    assert bus.get("test-session") is q2
    
    # Removing with non-matching queue (q1) should not remove q2
    bus.remove("test-session", q1)
    assert bus.get("test-session") is q2
    
    # Removing with matching queue (q2) should remove it
    bus.remove("test-session", q2)
    assert bus.get("test-session") is None
