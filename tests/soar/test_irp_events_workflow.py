import importlib

import pytest

from soar.tools.watermark import SeenStore

irp_events = importlib.import_module("soar.workflows.irp-events")


@pytest.fixture
def settings(tmp_path):
    return {
        "enabled": True,
        "seen_path": str(tmp_path / "seen.json"),
        "seen_ttl": 3600,
        "min_response_severity": 3,
        "response_workflow": "respond_basic",
        "orchestrator_url": "http://127.0.0.1:8000",
    }


@pytest.fixture
def seen(tmp_path):
    return SeenStore(str(tmp_path / "seen.json"), ttl=3600)


class EnqueueRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, workflow_name, context):
        self.calls.append((workflow_name, context))
        return f"job_{len(self.calls)}"


def _wf(settings, seen, enqueue):
    return irp_events.IrpEventsWorkflow(settings=settings, seen=seen, enqueue=enqueue)


def _payload(event="alert.created", alert=None):
    return {"payload": {"event": event, "ts": "2026-07-05T10:41:03Z", "alert": alert or {}}}


def test_registered_name_is_irp_events_with_dash():
    """SOC Core has /webhooks/irp-events hardwired — registry key must match."""
    from soar.workflows import WorkflowRegistry

    registry = WorkflowRegistry()
    registry.init()
    assert registry.get_class("irp-events") is irp_events.IrpEventsWorkflow
    meta = registry.get("irp-events")
    assert meta["type"] == "webhook"


def test_unknown_event_is_not_an_error(settings, seen):
    wf = _wf(settings, seen, EnqueueRecorder())
    result = wf.run(_payload(event="alert.deleted"))
    assert result["handled"] is False
    assert result["reason"] == "unknown event"


def test_unknown_event_execute_succeeds(settings, seen):
    """Forward-compat: unknown event must not fail the job."""
    wf = _wf(settings, seen, EnqueueRecorder())
    outcome = wf.execute(_payload(event="something.new"))
    assert outcome.success is True


def test_alert_created_high_severity_enqueues_response(settings, seen):
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    alert = {"id": 123, "severity": 3, "rule_name": "Brute force", "entity": "10.0.0.5"}
    result = wf.run(_payload(alert=alert))
    assert result["action"] == "response_enqueued"
    assert enqueue.calls == [
        ("respond_basic", {"alert_id": 123, "severity": 3, "rule_name": "Brute force", "entity": "10.0.0.5"})
    ]


def test_alert_created_low_severity_logged_only(settings, seen):
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    result = wf.run(_payload(alert={"id": 5, "severity": 2}))
    assert result["action"] == "logged"
    assert enqueue.calls == []


def test_shadow_alert_echo_filtered(settings, seen):
    """Events about our own shadow alerts must not trigger responses."""
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    alert = {"id": 7, "severity": 4, "tags": ["sys:soar", "soar:shadow"]}
    result = wf.run(_payload(alert=alert))
    assert result["action"] == "shadow_echo"
    assert enqueue.calls == []


def test_duplicate_alert_single_response(settings, seen):
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    alert = {"id": 9, "severity": 4}
    assert wf.run(_payload(alert=alert))["action"] == "response_enqueued"
    assert wf.run(_payload(alert=alert))["action"] == "duplicate"
    assert len(enqueue.calls) == 1


def test_non_created_events_logged_only(settings, seen):
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    for event in ("alert.merged", "alert.status_changed", "incident.created", "incident.status_changed"):
        result = wf.run(_payload(event=event, alert={"id": 11, "severity": 4}))
        assert result == {"handled": True, "event": event, "action": "logged"}
    assert enqueue.calls == []


def test_status_changed_does_not_mark_seen(settings, seen):
    """A missed alert.created must still be caught by the poller even if a
    later status_changed webhook arrived first."""
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    wf.run(_payload(event="alert.status_changed", alert={"id": 13, "severity": 4}))
    assert seen.is_seen("irp_seen:13") is False


def test_disabled_integration_ignores_event(settings, seen):
    settings["enabled"] = False
    enqueue = EnqueueRecorder()
    wf = _wf(settings, seen, enqueue)
    result = wf.run(_payload(alert={"id": 1, "severity": 4}))
    assert result["handled"] is False
    assert enqueue.calls == []


def test_alert_without_id_is_invalid_not_crash(settings, seen):
    wf = _wf(settings, seen, EnqueueRecorder())
    result = wf.run(_payload(alert={"severity": 4}))
    assert result["action"] == "invalid"
