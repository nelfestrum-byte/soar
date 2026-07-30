import socket
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


def _fake_socket(family):
    sock = MagicMock()
    sock.family = family
    return sock


def test_handle_socket_connect_private_address_blocks():
    from soar.audit_hook import _events, _handle

    _events.clear()
    sock = _fake_socket(socket.AF_INET)
    with pytest.raises(PermissionError):
        _handle("socket.connect", (sock, ("10.0.0.1", 80)))
    assert any(e["event"] == "socket.connect.blocked" for e in _events)
    _events.clear()


def test_handle_socket_connect_public_address_allowed():
    from soar.audit_hook import _events, _handle

    _events.clear()
    sock = _fake_socket(socket.AF_INET)
    _handle("socket.connect", (sock, ("8.8.8.8", 443)))
    assert any(e["event"] == "socket.connect" and "8.8.8.8" in e["address"] for e in _events)
    _events.clear()


def test_handle_socket_connect_non_inet_family_not_checked():
    from soar.audit_hook import _events, _handle

    _events.clear()
    sock = _fake_socket(socket.AF_UNIX if hasattr(socket, "AF_UNIX") else 99999)
    _handle("socket.connect", (sock, ("/tmp/x",)))
    assert len(_events) == 1
    assert _events[0]["event"] == "socket.connect"
    _events.clear()


def test_handle_open_records_path():
    from soar.audit_hook import _events, _handle

    _events.clear()
    _handle("open", ("/etc/passwd", "r", 0))
    assert _events[-1] == {"event": "open", "path": "/etc/passwd"}
    _events.clear()


def test_handle_subprocess_popen_records_executable():
    from soar.audit_hook import _events, _handle

    _events.clear()
    _handle("subprocess.Popen", ("/bin/sh", ["/bin/sh"], None, None))
    assert _events[-1] == {"event": "subprocess.Popen", "executable": "/bin/sh"}
    _events.clear()


def test_flush_writes_one_line_per_event_and_clears():
    from soar.audit_hook import _events, flush

    _events.clear()
    _events.append({"event": "open", "path": "/tmp/x"})
    _events.append({"event": "socket.connect", "address": "8.8.8.8"})

    with patch("soar.audit_hook._log") as mock_log:
        bound = MagicMock()
        mock_log.bind.return_value = bound
        flush()
        assert bound.info.call_count == 2

    assert _events == []


def test_flush_noop_on_empty_events():
    from soar.audit_hook import _events, flush

    _events.clear()
    with patch("soar.audit_hook._log") as mock_log:
        flush()
        mock_log.bind.assert_not_called()


def test_install_in_subprocess_does_not_break_normal_resolution():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import soar.audit_hook as h; h.install(); "
            "import socket; socket.getaddrinfo('localhost', None)"
        )],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_install_in_subprocess_blocks_private_connect():
    code = (
        "import soar.audit_hook as h, socket\n"
        "h.install()\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(1)\n"
        "try:\n"
        "    s.connect(('127.0.0.1', 1))\n"
        "    print('NOT_BLOCKED')\n"
        "except PermissionError:\n"
        "    print('BLOCKED')\n"
        "except OSError as e:\n"
        "    print('OTHER_OSERROR', e)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert "BLOCKED" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 0
