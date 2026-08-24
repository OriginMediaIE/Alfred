from types import SimpleNamespace

from services import operational_health as health


class _Task:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


def test_scheduler_distinguishes_running_dead_and_detached(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_INPROCESS_TASKS", "1")
    assert health._scheduler_health(SimpleNamespace())["status"] == "disabled"
    running = SimpleNamespace(_running=True, _task=_Task(False))
    assert health._scheduler_health(SimpleNamespace(task_scheduler=running))["status"] == "ok"
    dead = SimpleNamespace(_running=True, _task=_Task(True))
    assert health._scheduler_health(SimpleNamespace(task_scheduler=dead))["status"] == "down"


def test_embedding_health_exposes_counts_not_endpoint_details():
    store = SimpleNamespace(healthy=True, _lanes=[object(), object()])

    result = health._embedding_health(store, None)

    assert result["status"] == "ok"
    assert result["meta"] == {
        "configured_stores": 1, "healthy_stores": 1, "lanes": 2,
    }
    assert "url" not in str(result).lower()


def test_operational_report_has_every_local_dimension(monkeypatch):
    monkeypatch.setattr(health, "_database_health", lambda: health._svc("database", "ok", ""))
    monkeypatch.setattr(health, "_queue_health", lambda _state: health._svc("queue", "ok", "", depth=0))
    monkeypatch.setattr(health, "_google_capability_health", lambda _owner, name: health._svc(name, "disabled", ""))
    monkeypatch.setattr(health, "_transcription_health", lambda: health._svc("transcription", "disabled", ""))
    monkeypatch.setattr(health, "_file_storage_health", lambda: health._svc("file_storage", "ok", ""))
    monkeypatch.setenv("ODYSSEUS_INPROCESS_TASKS", "0")

    services = health.collect_operational_health(SimpleNamespace(), owner="owner")

    assert {item["name"] for item in services} == {
        "application", "database", "scheduler", "queue", "embedding_provider",
        "gmail", "calendar", "transcription", "file_storage",
    }
