"""Parses SOAR_AUDIT_EVENT lines written by soar.connectors._proxy.ConnectorProxy
into structured events for orchestrator.audit.service.record_job_event.

Format (pinned together with the writer, soar/connectors/_proxy.py):
    SOAR_AUDIT_EVENT connector.call target=<t> args=<a> kwargs=<k> duration_ms=<n> outcome=<o> job_id=<j>
    SOAR_AUDIT_EVENT connector.call.dry_run target=<t> args=<a> kwargs=<k> job_id=<j>

args=/kwargs= are str()-formatted Python literals, not re-parsed into
structures here — see spec [S6] for why (already redacted by the proxy;
parsing arbitrary repr() back into objects would be a strictly bigger risk
than the observability this buys).
"""

import re

_EVENT_RE = re.compile(
    r"SOAR_AUDIT_EVENT connector\.call(?P<dry_run>\.dry_run)? "
    r"target=(?P<target>\S+) args=(?P<args>.*?) kwargs=(?P<kwargs>.*?)"
    r"(?: duration_ms=(?P<duration_ms>\d+) outcome=(?P<outcome>\S+))?"
    r" job_id=(?P<job_id>\S*)\s*$"
)


def parse_audit_events(log_text: str) -> list[dict]:
    """Scan a job log (or any multi-line text) for SOAR_AUDIT_EVENT lines.
    Unparseable/unrelated lines are skipped, never raise."""
    events = []
    for line in log_text.splitlines():
        if "SOAR_AUDIT_EVENT" not in line:
            continue
        m = _EVENT_RE.search(line)
        if not m:
            continue
        duration_ms = m.group("duration_ms")
        events.append({
            "target": m.group("target"),
            "dry_run": m.group("dry_run") is not None,
            "duration_ms": int(duration_ms) if duration_ms is not None else None,
            "outcome": m.group("outcome"),
            "job_id": m.group("job_id"),
            "args": m.group("args"),
            "kwargs": m.group("kwargs"),
        })
    return events
