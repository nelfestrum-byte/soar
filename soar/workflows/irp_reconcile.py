"""Reconciliation poller — the guarantee behind the IRP webhook (contract §5.2,
plan Task 4).

The webhook is fire-and-forget on the SOC Core side (no retries): anything
missed while SOAR was down is picked up here. A missed webhook is a delay,
never a loss. Dedup with the webhook path is the shared SeenStore — an alert
that arrived through both produces exactly one response (same dispatch_alert).
"""

from datetime import UTC, datetime, timedelta

from soar.connectors import connectors
from soar.tools.irp_dispatch import dispatch_alert
from soar.tools.irp_settings import load_irp_settings
from soar.tools.watermark import SeenStore, WatermarkStore
from soar.workflows.base import ScheduledWorkflow

WATERMARK_KEY = "irp_reconcile"


class IrpReconcileWorkflow(ScheduledWorkflow):
    interval = 300

    def __init__(self, irp=None, settings: dict | None = None, seen=None, enqueue=None,
                 watermark=None, now: datetime | None = None):
        super().__init__()
        self._irp = irp
        self._settings = settings
        self._seen = seen
        self._enqueue = enqueue
        self._watermark = watermark
        self._now = now

    def run(self, context: dict) -> dict:
        settings = self._settings or load_irp_settings()
        if not settings.get("enabled"):
            self._logger.info("IRP integration disabled in config, cycle skipped")
            return {"skipped": "irp integration disabled"}

        irp = self._irp or getattr(connectors, settings["connector"])
        wm_store = self._watermark or WatermarkStore(settings["watermark_path"])
        seen = self._seen or SeenStore(settings["seen_path"], ttl=settings["seen_ttl"])
        now = self._now or datetime.now(UTC)

        watermark = wm_store.get(WATERMARK_KEY)
        if watermark is None:
            # first run: start from now − window, not from the epoch
            window = timedelta(minutes=int(settings["time_window_minutes"]))
            watermark = (now - window).isoformat()
            self._logger.info(f"no reconcile watermark, starting from {watermark}")

        # created_after filter is plan assumption Д-2 — if /list does not
        # support it yet, the extra alerts are absorbed by SeenStore dedup
        resp = irp.list_alerts(created_after=watermark, limit=500)
        alerts = resp.get("alerts") or []

        counters = {"fetched": len(alerts), "response_enqueued": 0, "duplicate": 0,
                    "logged": 0, "shadow_echo": 0, "invalid": 0}
        max_created = None
        for alert in alerts:
            result = dispatch_alert(
                alert,
                seen=seen,
                settings=settings,
                log=self._logger,
                enqueue=self._enqueue,
                source="reconcile",
            )
            counters[result["action"]] = counters.get(result["action"], 0) + 1
            created_at = alert.get("created_at")
            if created_at and (max_created is None or created_at > max_created):
                max_created = created_at

        if max_created is not None:
            wm_store.set(WATERMARK_KEY, max_created)

        counters["watermark"] = max_created or watermark
        return counters
