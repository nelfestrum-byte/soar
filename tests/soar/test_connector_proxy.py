from typing import ClassVar
from unittest.mock import patch

import pytest

from soar import runtime_state
from soar.connectors._proxy import ConnectorProxy
from soar.connectors.base import BaseConnector


class _FakeConnector(BaseConnector):
    HIDDEN_FIELDS: ClassVar[set[str]] = {"password"}
    MUTATING_METHODS: ClassVar[set[str]] = {"send"}

    def __init__(self):
        super().__init__(instance_name="fake1")
        self.calls = []

    def _connect_impl(self):
        pass

    def get_thing(self, x):
        self.calls.append(("get_thing", x))
        return {"x": x}

    def send(self, to, password=None):
        self.calls.append(("send", to, password))
        return {"sent": True}

    def boom(self):
        raise ValueError("kaboom")


@pytest.fixture(autouse=True)
def _reset_dry_run():
    runtime_state.set_dry_run(False)
    yield
    runtime_state.set_dry_run(False)


def test_public_method_call_delegates_and_returns_value():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    result = proxy.get_thing("abc")
    assert result == {"x": "abc"}
    assert inst.calls == [("get_thing", "abc")]


def test_private_attr_returned_as_is_no_wrapper():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    assert proxy._instance is inst
    assert proxy.instance_name == "fake1"  # non-callable public attr — passthrough


def test_call_logs_audit_event_with_target():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    with patch("soar.connectors._proxy._log") as mock_log:
        proxy.get_thing("abc")
    bound = mock_log.bind.return_value
    assert bound.info.call_count == 1
    line = bound.info.call_args[0][0]
    assert "SOAR_AUDIT_EVENT connector.call target=fake_type.fake1.get_thing" in line
    assert "duration_ms=" in line
    assert "outcome=ok" in line


def test_hidden_fields_redacted_in_log_not_in_call():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    with patch("soar.connectors._proxy._log") as mock_log:
        proxy.send(to="bob", password="s3cr3t")
    assert inst.calls == [("send", "bob", "s3cr3t")]  # real call unredacted
    bound = mock_log.bind.return_value
    line = bound.info.call_args[0][0]
    assert "s3cr3t" not in line
    assert "'password': '***'" in line


def test_mutating_method_blocked_in_dry_run():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    runtime_state.set_dry_run(True)
    with patch("soar.connectors._proxy._log") as mock_log:
        result = proxy.send(to="bob")
    assert result is None
    assert inst.calls == []  # method never called
    bound = mock_log.bind.return_value
    line = bound.info.call_args[0][0]
    assert "connector.call.dry_run" in line


def test_mutating_method_runs_normally_when_not_dry_run():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    runtime_state.set_dry_run(False)
    result = proxy.send(to="bob")
    assert result == {"sent": True}
    assert inst.calls == [("send", "bob", None)]


def test_non_mutating_method_runs_even_in_dry_run():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    runtime_state.set_dry_run(True)
    result = proxy.get_thing("abc")
    assert result == {"x": "abc"}


def test_exception_logged_and_reraised():
    inst = _FakeConnector()
    proxy = ConnectorProxy(inst, "fake_type")
    with patch("soar.connectors._proxy._log") as mock_log:
        with pytest.raises(ValueError, match="kaboom"):
            proxy.boom()
    bound = mock_log.bind.return_value
    line = bound.info.call_args[0][0]
    assert "outcome=error:ValueError" in line
