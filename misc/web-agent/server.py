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
across restarts, no multi-session support (see spec Non-goals).

Turns run asynchronously in a background thread, not inside the request
handler: a wrapped CLI turn can legitimately take the better part of an hour
(real sysadmin/incident-response work, not a chat reply), and blocking the
HTTP handler for that long means no visibility and no way to intervene until
it's over — which is exactly the failure mode this module exists to avoid.
``POST /message`` starts a turn and returns immediately; ``GET /status``
polls the transcript accumulated so far (written incrementally as the CLI
streams output, not just once at the end); ``POST /stop`` interrupts the
running turn (SIGINT, escalating to SIGKILL). Exactly one turn may be in
flight at a time — a second ``POST /message`` while one is running is
rejected, since two concurrent invocations against the same ``--resume``
session would race.

Stdlib only: ``http.server``, ``json``, ``subprocess``, ``threading``,
``uuid``, ``time``, ``pathlib``, ``argparse``, ``importlib.util``.
"""

import argparse
import importlib.util
import json
import signal
import subprocess
import threading
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


def _build_argv(settings, session_id, is_new_session, text):
    template = settings.NEW_SESSION_ARGS if is_new_session else settings.RESUME_SESSION_ARGS
    session_args = [arg.format(session_id=session_id) for arg in template]
    argv = list(settings.BASE_ARGS) + session_args
    if settings.PROMPT_MODE == "arg":
        argv = argv + [text]
    return argv


class Turn:
    """One in-flight or just-completed CLI turn: streamed output, live status."""

    def __init__(self, session_id, request_text):
        self.session_id = session_id
        self.request_text = request_text
        self.started_at = time.time()
        self.finished_at = None
        self.process = None
        self.returncode = None
        self.stopped_by_user = False
        self.timed_out = False
        self.error = None
        self._lock = threading.Lock()
        self._stdout_lines = []
        self._stderr_lines = []

    def append_stdout(self, line):
        with self._lock:
            self._stdout_lines.append(line)

    def append_stderr(self, line):
        with self._lock:
            self._stderr_lines.append(line)

    def snapshot(self):
        with self._lock:
            stdout_lines = list(self._stdout_lines)
            stderr_lines = list(self._stderr_lines)
        return {
            "session_id": self.session_id,
            "running": self.finished_at is None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": (self.finished_at or time.time()) - self.started_at,
            "returncode": self.returncode,
            "stopped_by_user": self.stopped_by_user,
            "timed_out": self.timed_out,
            "error": self.error,
            "stdout_lines": stdout_lines,
            "stderr_lines": stderr_lines,
        }


class BridgeState:
    """Holds the one conversation this bridge process is responsible for."""

    def __init__(self, settings):
        self.settings = settings
        self.session_id = None
        self.turn = None  # current or most recently finished Turn
        self.lock = threading.Lock()


def _pump_stream(stream, sink_append, log_file, prefix):
    for line in stream:
        line = line.rstrip("\n")
        sink_append(line)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"{prefix} {line}\n")
    stream.close()


def _run_turn(settings, turn, argv):
    log_path = Path(settings.LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"=== {timestamp} REQUEST session={turn.session_id} ===\n{turn.request_text}\n--- stream ---\n")

    run_kwargs = dict(cwd=settings.CWD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    run_kwargs["stdin"] = subprocess.PIPE if settings.PROMPT_MODE == "stdin" else subprocess.DEVNULL

    try:
        proc = subprocess.Popen(argv, **run_kwargs)
    except FileNotFoundError as exc:
        turn.error = f"CLI binary not found: {exc}"
        turn.finished_at = time.time()
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"--- error: {turn.error} ---\n\n")
        return

    turn.process = proc

    if settings.PROMPT_MODE == "stdin":
        proc.stdin.write(turn.request_text)
        proc.stdin.close()

    watchdog_fired = threading.Event()

    def _timeout_killer():
        if not watchdog_fired.wait(timeout=settings.TIMEOUT_S):
            if proc.poll() is None:
                turn.timed_out = True
                proc.kill()

    threading.Thread(target=_timeout_killer, daemon=True).start()

    t_out = threading.Thread(target=_pump_stream, args=(proc.stdout, turn.append_stdout, log_path, "OUT"), daemon=True)
    t_err = threading.Thread(target=_pump_stream, args=(proc.stderr, turn.append_stderr, log_path, "ERR"), daemon=True)
    t_out.start()
    t_err.start()

    proc.wait()
    watchdog_fired.set()
    t_out.join()
    t_err.join()

    turn.returncode = proc.returncode
    turn.finished_at = time.time()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"--- end session={turn.session_id} returncode={turn.returncode} "
            f"duration_s={turn.finished_at - turn.started_at:.3f} "
            f"stopped_by_user={turn.stopped_by_user} timed_out={turn.timed_out} ---\n\n"
        )


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
            elif self.path == "/status":
                with state.lock:
                    turn = state.turn
                if turn is None:
                    self._send_json(200, {"running": False, "session_id": state.session_id})
                else:
                    self._send_json(200, turn.snapshot())
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/message":
                self._handle_message()
            elif self.path == "/stop":
                self._handle_stop()
            else:
                self._send_json(404, {"error": "not found"})

        def _handle_message(self):
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
            with state.lock:
                if state.turn is not None and state.turn.finished_at is None:
                    self._send_json(409, {"error": "a turn is already in progress", "status": state.turn.snapshot()})
                    return
                is_new_session = state.session_id is None
                session_id = state.session_id if not is_new_session else str(uuid.uuid4())
                state.session_id = session_id
                turn = Turn(session_id, text)
                state.turn = turn

            argv = _build_argv(settings, session_id, is_new_session, text)
            threading.Thread(target=_run_turn, args=(settings, turn, argv), daemon=True).start()
            self._send_json(202, {"status": "started", "session_id": session_id})

        def _handle_stop(self):
            with state.lock:
                turn = state.turn
            if turn is None or turn.finished_at is not None:
                self._send_json(400, {"error": "no turn in progress"})
                return
            turn.stopped_by_user = True
            proc = turn.process
            if proc is not None and proc.poll() is None:
                proc.send_signal(signal.SIGINT)

                def _escalate():
                    time.sleep(10)
                    if proc.poll() is None:
                        proc.kill()

                threading.Thread(target=_escalate, daemon=True).start()
            self._send_json(200, {"status": "stopping"})

    return BridgeRequestHandler


def build_server(settings):
    """Build (but do not start) the HTTP server.

    Handlers never block for the duration of a CLI turn (turns run in a
    background thread — see ``_run_turn``), so a single-threaded
    ``http.server.HTTPServer`` is enough: ``POST /message`` returns as soon
    as the turn is *started*, leaving the server free to answer
    ``GET /status``/``POST /stop`` while that turn runs. Exactly one turn in
    flight at a time is still enforced explicitly (see ``_handle_message``),
    independent of the server's threading model.
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
