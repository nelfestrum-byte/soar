"""IRP lifecycle events receiver (contract §5, plan Task 3).

The filename is dash-cased on purpose: the workflow registry keys by filename
and SOC Core has ``SOAR_WEBHOOK_URL = http://<host>:8000/webhooks/irp-events``
hardwired — the registration name must be exactly ``irp-events``.

The orchestrator validates X-Webhook-Token against the class ``token`` and
delivers the JSON body in ``context["payload"]``. The token comes from the
SOAR_WEBHOOK_TOKEN env of the orchestrator process (agreed with SOC Core);
if unset the token is empty and the webhook endpoint fails closed with 403.
"""

import os

from soar.logger import get_logger
from soar.tools.irp_dispatch import dispatch_alert
from soar.tools.irp_settings import load_irp_settings
from soar.tools.watermark import SeenStore
from soar.workflows.base import WebhookWorkflow

_log = get_logger("workflow.irp-events")

# Contract §5.1. Unknown events are logged and acknowledged, never an error —
# SOC Core may add event types before we handle them (forward-compat).
KNOWN_EVENTS = {
    "alert.created",
    "alert.merged",
    "alert.status_changed",
    "incident.created",
    "incident.status_changed",
}


class IrpEventsWorkflow(WebhookWorkflow):
    path = "/webhooks/irp-events"
    token = os.environ.get("SOAR_WEBHOOK_TOKEN", "")

    def __init__(self, settings: dict | None = None, seen=None, enqueue=None):
        super().__init__()
        self._settings = settings
        self._seen = seen
        self._enqueue = enqueue

    def run(self, context: dict) -> dict:
        settings = self._settings or load_irp_settings()
        if not settings.get("enabled"):
            self._logger.warning("IRP integration disabled in config, event ignored")
            return {"handled": False, "reason": "irp integration disabled"}

        payload = context.get("payload") or {}
        event = payload.get("event")
        if event not in KNOWN_EVENTS:
            self._logger.warning(f"unknown IRP event '{event}', ignored (forward-compat)")
            return {"handled": False, "event": event, "reason": "unknown event"}

        if event != "alert.created":
            # groundwork for future playbooks: acknowledged and logged only
            self._logger.info(f"IRP event '{event}' received, no dispatch rule (logged)")
            return {"handled": True, "event": event, "action": "logged"}

        seen = self._seen or SeenStore(settings["seen_path"], ttl=settings["seen_ttl"])
        result = dispatch_alert(
            payload.get("alert") or {},
            seen=seen,
            settings=settings,
            log=self._logger,
            enqueue=self._enqueue,
            source="webhook",
        )
        return {"handled": True, "event": event, **result}
