"""Shared dispatch of IRP alerts to response workflows.

Used by both delivery paths — the webhook receiver (fast path) and the
reconciliation poller (guarantee path) — so an alert produces exactly one
response regardless of how it arrived (plan Task 3/4: one function, no copy).

Dedup is durable (SeenStore, key ``irp_seen:{alert_id}``, TTL 24h): the path
that processes the alert's creation first marks it, the other skips it.
Every "no response" decision is a logged action with a reason — no silent drops.
"""

from collections.abc import Callable

import requests

# MVP dispatch rules live in code; the echo filter is mandatory — events about
# our own shadow alerts must not trigger responses, otherwise the shadow run
# starts reacting to copies (plan Task 3).
SHADOW_TAG = "soar:shadow"


def make_enqueue(orchestrator_url: str, timeout: int = 10) -> Callable[[str, dict], str]:
    """Enqueue a workflow job through the orchestrator API (workflows run in a
    subprocess and have no direct access to the job manager)."""

    url = f"{orchestrator_url.rstrip('/')}/jobs"

    def enqueue(workflow_name: str, context: dict) -> str:
        resp = requests.post(
            url, json={"workflow_name": workflow_name, "context": context}, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("id", "")

    return enqueue


def dispatch_alert(
    alert: dict,
    *,
    seen,
    settings: dict,
    log,
    enqueue: Callable[[str, dict], str] | None = None,
    source: str = "webhook",
) -> dict:
    """Decide and (maybe) enqueue a response for a newly created IRP alert.

    Returns {"action": ..., "alert_id": ..., ["job_id"|"reason"]: ...}.
    Actions: response_enqueued | logged | duplicate | shadow_echo | invalid.
    """
    alert_id = alert.get("id")
    if alert_id is None:
        log.warning(f"[{source}] alert without id, ignored: {alert}")
        return {"action": "invalid", "alert_id": None, "reason": "missing id"}

    seen_key = f"irp_seen:{alert_id}"
    if seen.is_seen(seen_key):
        log.info(f"[{source}] alert {alert_id} already seen, skipping (dedup)")
        return {"action": "duplicate", "alert_id": alert_id}
    seen.mark(seen_key)

    tags = alert.get("tags") or []
    if SHADOW_TAG in tags:
        log.info(f"[{source}] alert {alert_id} is our shadow copy, no response (echo filter)")
        return {"action": "shadow_echo", "alert_id": alert_id}

    severity = int(alert.get("severity") or 0)
    min_severity = int(settings.get("min_response_severity", 3))
    if severity < min_severity:
        log.info(
            f"[{source}] alert {alert_id} severity {severity} < {min_severity}, logged only"
        )
        return {"action": "logged", "alert_id": alert_id, "reason": "below severity"}

    context = {
        "alert_id": alert_id,
        "severity": severity,
        "rule_name": alert.get("rule_name") or "",
        "entity": alert.get("entity") or "",
    }
    workflow_name = settings.get("response_workflow", "respond_basic")
    if enqueue is None:
        enqueue = make_enqueue(settings.get("orchestrator_url", "http://127.0.0.1:8000"))
    job_id = enqueue(workflow_name, context)
    log.info(f"[{source}] alert {alert_id} → response '{workflow_name}' job {job_id}")
    return {"action": "response_enqueued", "alert_id": alert_id, "job_id": job_id}
