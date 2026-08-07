"""Generic CLI-to-HTTP bridge.

Spawns and re-invokes a configured headless CLI as a subprocess per request,
exposing it as ``POST /message``. Two independent processes that can each
reach this bridge over HTTP can hold a conversation with the wrapped CLI
without either one needing tool-level access to the other — see
``docs/compose/specs/2026-08-07-web-agent-bridge-design.md``.

Genericity comes entirely from the settings file (``settings.py`` by
default, or ``--settings <path>``), not from this module: CLI executable
path, static launch args, working directory, how prompt text is delivered
(argv vs stdin), and two argv templates (``NEW_SESSION_ARGS`` /
``RESUME_SESSION_ARGS``) each containing a ``{session_id}`` placeholder.
This module never hardcodes anything about a specific CLI — it only knows
"argv in, stdout/stderr/returncode out."

The bridge holds exactly one conversation per running process: one
in-memory session id, created on first ``POST /message``, no persistence
across restarts, no multi-session support (see spec Non-goals). The HTTP
server is deliberately single-threaded (``http.server.HTTPServer``, not
``ThreadingHTTPServer``) so CLI turns are strictly serialized — two
concurrent invocations against the same resumed session would race.

Stdlib only: ``http.server``, ``json``, ``subprocess``, ``uuid``, ``time``,
``pathlib``, ``argparse``, ``importlib.util``.
"""

import argparse
import importlib.util
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def load_settings(path):
    """Load a settings module from an arbitrary file path."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location("web_agent_bridge_settings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BridgeState:
    """Holds the one conversation this bridge process is responsible for."""

    def __init__(self, settings):
        self.settings = settings
        self.session_id = None


def _append_transcript(log_file, session_id, request_text, result, duration_s):
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    block = (
        f"=== {timestamp} ===\n"
        f"session_id: {session_id}\n"
        f"duration_s: {duration_s:.3f}\n"
        f"returncode: {result.returncode}\n"
        f"--- request ---\n{request_text}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}\n"
        "\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(block)


def _build_argv(settings, session_id, is_new_session, text):
    template = settings.NEW_SESSION_ARGS if is_new_session else settings.RESUME_SESSION_ARGS
    session_args = [arg.format(session_id=session_id) for arg in template]
    argv = list(settings.BASE_ARGS) + session_args
    if settings.PROMPT_MODE == "arg":
        argv = argv + [text]
    return argv


def make_handler_class(state):
    class BridgeRequestHandler(BaseHTTPRequestHandler):
        server_version = "WebAgentBridge/1.0"

        def log_message(self, fmt, *args):
            # Keep stdout/stderr quiet; the transcript log is the audit trail.
            pass

        def _send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "session_id": state.session_id})
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/message":
                self._send_json(404, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
                text = body["text"]
                if not isinstance(text, str):
                    raise ValueError("'text' must be a string")
            except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError, TypeError):
                self._send_json(400, {"error": "malformed request body: expected {\"text\": \"...\"}"})
                return

            settings = state.settings
            is_new_session = state.session_id is None
            session_id = state.session_id if not is_new_session else str(uuid.uuid4())

            argv = _build_argv(settings, session_id, is_new_session, text)

            run_kwargs = dict(
                cwd=settings.CWD,
                capture_output=True,
                text=True,
                timeout=settings.TIMEOUT_S,
            )
            if settings.PROMPT_MODE == "stdin":
                run_kwargs["input"] = text
            else:
                run_kwargs["stdin"] = subprocess.DEVNULL

            start = time.time()
            try:
                result = subprocess.run(argv, **run_kwargs)
            except subprocess.TimeoutExpired:
                self._send_json(504, {"error": "subprocess timed out"})
                return
            except FileNotFoundError as exc:
                self._send_json(502, {"error": f"CLI binary not found: {exc}"})
                return
            duration_s = time.time() - start

            state.session_id = session_id

            _append_transcript(settings.LOG_FILE, session_id, text, result, duration_s)

            self._send_json(
                200,
                {
                    "session_id": session_id,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "duration_s": duration_s,
                },
            )

    return BridgeRequestHandler


def build_server(settings):
    """Build (but do not start) the single-threaded HTTP server.

    Deliberately ``http.server.HTTPServer`` and not ``ThreadingHTTPServer``:
    CLI turns must be strictly sequential, since two concurrent invocations
    against the same resumed session would race.
    """
    state = BridgeState(settings)
    handler_cls = make_handler_class(state)
    httpd = HTTPServer((settings.HOST, settings.PORT), handler_cls)
    httpd.bridge_state = state
    return httpd


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generic CLI-to-HTTP bridge for blind agent-to-agent testing")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path(__file__).resolve().parent / "settings.py",
        help="Path to a settings module (default: sibling settings.py)",
    )
    args = parser.parse_args(argv)

    settings = load_settings(args.settings)
    httpd = build_server(settings)
    print(f"web-agent bridge listening on {settings.HOST}:{settings.PORT} (settings: {args.settings})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
