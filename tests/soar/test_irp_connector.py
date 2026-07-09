from unittest.mock import MagicMock, patch

from soar.connectors.irp.irp import IRPConnector


def _connected(**overrides) -> tuple[IRPConnector, MagicMock]:
    params = {
        "instance_name": "test_irp",
        "base_url": "http://irp.local:5000/",
        "api_token": "tok123",
        **overrides,
    }
    conn = IRPConnector(**params)
    session = MagicMock()
    conn._session = session
    conn._connected = True
    return conn, session


def _resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_irp_init_strips_trailing_slash():
    conn = IRPConnector(instance_name="test_irp", base_url="http://irp.local:5000/", api_token="tok")
    assert conn.base_url == "http://irp.local:5000"
    assert conn.is_connected is False


def test_irp_connect_sets_token_header():
    conn = IRPConnector(instance_name="test_irp", base_url="http://irp.local:5000", api_token="tok123")
    conn._connect_impl()
    assert conn._session is not None
    assert conn._session.headers["X-API-Token"] == "tok123"


def test_irp_ingest_alert():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"id": 42, "action": "created"})

    result = conn.ingest_alert(
        title="[CRIT] Test rule",
        source_ref="soc-abc123-20260705-10",
        severity=4,
        rule_name="Test rule",
        entity="10.0.0.5",
        triage_run_id="srun_1",
        backfill=True,
    )
    assert result == {"id": 42, "action": "created"}
    method, url = session.request.call_args[0]
    assert method == "POST"
    assert url == "http://irp.local:5000/api/v2/alerts/ingest"
    body = session.request.call_args[1]["json"]
    assert body["source_ref"] == "soc-abc123-20260705-10"
    assert body["backfill"] is True
    assert body["triage_run_id"] == "srun_1"


def test_irp_ingest_alert_skipped_passthrough():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"id": None, "action": "skipped"})
    result = conn.ingest_alert(title="ET INFO noise", source_ref="soc-x-1")
    assert result["action"] == "skipped"


def test_irp_transition_alert_ok():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"ok": True})
    result = conn.transition_alert(7, "acknowledged")
    assert result == {"ok": True}
    body = session.request.call_args[1]["json"]
    assert body == {"status": "acknowledged", "skip_response_steps": False}


def test_irp_transition_alert_forbidden_returns_ok_false():
    conn, session = _connected()
    session.request.return_value = _resp(
        400, {"detail": "transition new -> investigating not allowed"}
    )
    result = conn.transition_alert(7, "investigating")
    assert result["ok"] is False
    assert result["status_code"] == 400
    assert "not allowed" in result["error"]


def test_irp_transition_alert_steps_incomplete_409():
    conn, session = _connected()
    session.request.return_value = _resp(
        409, {"detail": {"ok": False, "error": "response_steps_incomplete"}}
    )
    result = conn.transition_alert(7, "resolved")
    assert result["ok"] is False
    assert result["status_code"] == 409
    assert result["error"]["error"] == "response_steps_incomplete"


def test_irp_add_comment():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"ok": True, "id": 3})
    result = conn.add_comment(7, "SOAR: заблокирован IP 1.2.3.4 (job srun_1)")
    assert result["ok"] is True
    method, url = session.request.call_args[0]
    assert method == "POST"
    assert url == "http://irp.local:5000/api/v2/alerts/7/comments"


def test_irp_response_steps_roundtrip():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"steps": [{"id": 1, "done": False}]})
    result = conn.ensure_response_steps(7, ["Шаг 1", "Шаг 2"])
    assert result["steps"][0]["id"] == 1

    session.request.return_value = _resp(200, {"ok": True})
    result = conn.toggle_response_step(7, 1, done=True)
    assert result["ok"] is True
    method, url = session.request.call_args[0]
    assert method == "PATCH"
    assert url == "http://irp.local:5000/api/v2/alerts/7/response-steps/1"


def test_irp_list_alerts_params_passthrough():
    conn, session = _connected()
    session.request.return_value = _resp(200, {"alerts": [], "total": 0})
    conn.list_alerts(status="new", limit=50)
    assert session.request.call_args[1]["params"] == {"status": "new", "limit": 50}


def test_irp_heartbeat_no_redis_host():
    conn, _ = _connected()
    assert conn.send_heartbeat() is False


def test_irp_heartbeat_setex():
    conn, _ = _connected(redis_host="10.0.0.1", redis_password="pw", heartbeat_ttl=180)
    fake_redis = MagicMock()
    with patch.dict("sys.modules", {"redis": MagicMock(Redis=MagicMock(return_value=fake_redis))}):
        assert conn.send_heartbeat() is True
    fake_redis.setex.assert_called_once_with("orchestrator_heartbeat", 180, "alive")


def test_irp_heartbeat_redis_error_returns_false():
    conn, _ = _connected(redis_host="10.0.0.1")
    fake_redis = MagicMock()
    fake_redis.setex.side_effect = ConnectionError("down")
    conn._redis = fake_redis
    assert conn.send_heartbeat() is False


def test_irp_disconnect_closes_both():
    conn, session = _connected()
    fake_redis = MagicMock()
    conn._redis = fake_redis
    conn.disconnect()
    session.close.assert_called_once()
    fake_redis.close.assert_called_once()
    assert conn.is_connected is False
    assert conn._session is None
    assert conn._redis is None
