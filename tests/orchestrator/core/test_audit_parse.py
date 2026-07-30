from orchestrator.core.audit_parse import parse_audit_events


def test_parse_normal_event():
    line = (
        "2026-07-30 10:00:00 | INFO | connector.proxy | "
        "SOAR_AUDIT_EVENT connector.call target=virus_total.vt_main.get_ip_report "
        "args=('1.2.3.4',) kwargs={} duration_ms=120 outcome=ok job_id=abc123"
    )
    events = parse_audit_events(line)
    assert events == [
        {
            "target": "virus_total.vt_main.get_ip_report",
            "dry_run": False,
            "duration_ms": 120,
            "outcome": "ok",
            "job_id": "abc123",
            "args": "('1.2.3.4',)",
            "kwargs": "{}",
        }
    ]


def test_parse_dry_run_event_no_duration():
    line = (
        "SOAR_AUDIT_EVENT connector.call.dry_run target=smtp.prod.send_email "
        "args=() kwargs={'to': 'a@b.com'} job_id=xyz"
    )
    events = parse_audit_events(line)
    assert len(events) == 1
    e = events[0]
    assert e["dry_run"] is True
    assert e["duration_ms"] is None
    assert e["target"] == "smtp.prod.send_email"
    assert e["job_id"] == "xyz"


def test_parse_error_outcome_recognized_as_non_ok():
    line = (
        "SOAR_AUDIT_EVENT connector.call target=ssh.host1.exec_command "
        "args=('ls',) kwargs={} duration_ms=15 outcome=error:ValueError job_id=j1"
    )
    events = parse_audit_events(line)
    assert events[0]["outcome"] == "error:ValueError"
    assert events[0]["outcome"] != "ok"


def test_line_without_prefix_ignored():
    log = "some ordinary log line\nanother line\n"
    assert parse_audit_events(log) == []


def test_empty_or_malformed_log_returns_empty_list():
    assert parse_audit_events("") == []
    assert parse_audit_events("garbage\n\x00\x01") == []


def test_multiple_events_in_multiline_log():
    log = "\n".join(
        [
            "irrelevant line",
            "SOAR_AUDIT_EVENT connector.call target=a.b.c args=() kwargs={} duration_ms=1 outcome=ok job_id=j1",
            '{"success": true, "data": {}, "error": null}',
            "SOAR_AUDIT_EVENT connector.call target=d.e.f args=() kwargs={} duration_ms=2 outcome=ok job_id=j1",
        ]
    )
    events = parse_audit_events(log)
    assert len(events) == 2
    assert events[0]["target"] == "a.b.c"
    assert events[1]["target"] == "d.e.f"


def test_empty_job_id_parses_as_empty_string():
    line = "SOAR_AUDIT_EVENT connector.call target=a.b.c args=() kwargs={} duration_ms=1 outcome=ok job_id="
    events = parse_audit_events(line)
    assert events[0]["job_id"] == ""
