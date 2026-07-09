import importlib
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from soar.tools.watermark import SeenStore, WatermarkStore
from soar.workflows.irp_reconcile import IrpReconcileWorkflow

irp_events = importlib.import_module("soar.workflows.irp-events")

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path):
    return {
        "enabled": True,
        "seen_path": str(tmp_path / "seen.json"),
        "seen_ttl": 3600,
        "watermark_path": str(tmp_path / "wm.json"),
        "time_window_minutes": 10,
        "min_response_severity": 3,
        "response_workflow": "respond_basic",
    }


class EnqueueRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, workflow_name, context):
        self.calls.append((workflow_name, context))
        return f"job_{len(self.calls)}"


def _wf(settings, alerts, enqueue, tmp_path):
    irp = MagicMock()
    irp.list_alerts.return_value = {"alerts": alerts, "total": len(alerts)}
    return (
        IrpReconcileWorkflow(
            irp=irp,
            settings=settings,
            seen=SeenStore(settings["seen_path"], ttl=3600),
            enqueue=enqueue,
            watermark=WatermarkStore(settings["watermark_path"]),
            now=NOW,
        ),
        irp,
    )


def test_first_run_starts_from_now_minus_window(settings, tmp_path):
    wf, irp = _wf(settings, [], EnqueueRecorder(), tmp_path)
    wf.run({})
    created_after = irp.list_alerts.call_args[1]["created_after"]
    assert created_after == "2026-07-05T11:50:00+00:00"


def test_unseen_alert_dispatched(settings, tmp_path):
    enqueue = EnqueueRecorder()
    alerts = [{"id": 1, "severity": 4, "rule_name": "R", "entity": "h1",
               "created_at": "2026-07-05T11:55:00+00:00"}]
    wf, _ = _wf(settings, alerts, enqueue, tmp_path)
    result = wf.run({})
    assert result["response_enqueued"] == 1
    assert enqueue.calls[0][1]["alert_id"] == 1


def test_seen_alert_skipped(settings, tmp_path):
    enqueue = EnqueueRecorder()
    alerts = [{"id": 1, "severity": 4, "created_at": "2026-07-05T11:55:00+00:00"}]
    SeenStore(settings["seen_path"], ttl=3600).mark("irp_seen:1")
    wf, _ = _wf(settings, alerts, enqueue, tmp_path)
    result = wf.run({})
    assert result["duplicate"] == 1
    assert enqueue.calls == []


def test_watermark_moves_to_max_created_at(settings, tmp_path):
    alerts = [
        {"id": 1, "severity": 1, "created_at": "2026-07-05T11:52:00+00:00"},
        {"id": 2, "severity": 1, "created_at": "2026-07-05T11:58:00+00:00"},
        {"id": 3, "severity": 1, "created_at": "2026-07-05T11:55:00+00:00"},
    ]
    wf, _ = _wf(settings, alerts, EnqueueRecorder(), tmp_path)
    result = wf.run({})
    assert result["watermark"] == "2026-07-05T11:58:00+00:00"
    assert WatermarkStore(settings["watermark_path"]).get("irp_reconcile") == "2026-07-05T11:58:00+00:00"


def test_no_alerts_watermark_not_advanced(settings, tmp_path):
    store = WatermarkStore(settings["watermark_path"])
    store.set("irp_reconcile", "2026-07-05T11:00:00+00:00")
    wf, irp = _wf(settings, [], EnqueueRecorder(), tmp_path)
    result = wf.run({})
    assert irp.list_alerts.call_args[1]["created_after"] == "2026-07-05T11:00:00+00:00"
    assert store.get("irp_reconcile") == "2026-07-05T11:00:00+00:00"
    assert result["fetched"] == 0


def test_webhook_then_poller_single_response(settings, tmp_path):
    """Plan Task 4: an alert delivered via both webhook and poller → exactly
    one response. Shared SeenStore file is the dedup point."""
    enqueue = EnqueueRecorder()
    alert = {"id": 42, "severity": 4, "rule_name": "R", "entity": "h",
             "created_at": "2026-07-05T11:59:00+00:00"}

    webhook = irp_events.IrpEventsWorkflow(
        settings=settings, seen=SeenStore(settings["seen_path"], ttl=3600), enqueue=enqueue
    )
    webhook.run({"payload": {"event": "alert.created", "alert": alert}})

    wf, _ = _wf(settings, [alert], enqueue, tmp_path)
    result = wf.run({})

    assert len(enqueue.calls) == 1
    assert result["duplicate"] == 1


def test_shadow_alerts_not_responded(settings, tmp_path):
    enqueue = EnqueueRecorder()
    alerts = [{"id": 5, "severity": 4, "tags": ["sys:soar", "soar:shadow"],
               "created_at": "2026-07-05T11:59:00+00:00"}]
    wf, _ = _wf(settings, alerts, enqueue, tmp_path)
    result = wf.run({})
    assert result["shadow_echo"] == 1
    assert enqueue.calls == []


def test_disabled_integration_skips(settings, tmp_path):
    settings["enabled"] = False
    wf, irp = _wf(settings, [], EnqueueRecorder(), tmp_path)
    result = wf.run({})
    assert result == {"skipped": "irp integration disabled"}
    irp.list_alerts.assert_not_called()
