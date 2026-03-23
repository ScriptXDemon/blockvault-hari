from __future__ import annotations

from blockvault_api.config import reset_settings_cache
from blockvault_api.redaction_jobs import dispatch_redaction_job
from blockvault_api.redaction_jobs import _worker_ping


def test_dispatch_uses_inline_fallback_when_worker_not_configured(monkeypatch):
    calls: list[str] = []

    def fake_launch(job_id: str) -> None:
        calls.append(job_id)

    monkeypatch.setattr("blockvault_api.redaction_jobs.launch_inline_redaction_job", fake_launch)
    monkeypatch.setattr("blockvault_api.redaction_jobs.get_database", lambda: type("DB", (), {"redaction_jobs": type("Jobs", (), {"update_one": staticmethod(lambda *args, **kwargs: None)})()})())
    result = dispatch_redaction_job("redact_job_1")
    assert result == {"execution_mode": "inline_fallback", "task_id": None}
    assert calls == ["redact_job_1"]


def test_worker_ping_uses_configured_timeout(monkeypatch):
    class FakeInspect:
        def ping(self):
            return {"celery@test": {"ok": "pong"}}

    class FakeControl:
        def __init__(self):
            self.inspect_timeout = None

        def inspect(self, timeout):
            self.inspect_timeout = timeout
            return FakeInspect()

        def ping(self, timeout):
            raise AssertionError("fallback ping should not be used when inspect succeeds")

    class FakeClient:
        def __init__(self):
            self.control = FakeControl()

    monkeypatch.setenv("BLOCKVAULT_CELERY_PING_TIMEOUT_SECONDS", "2.5")
    reset_settings_cache()
    try:
        client = FakeClient()
        assert _worker_ping(client) is True
        assert client.control.inspect_timeout == 2.5
    finally:
        reset_settings_cache()
