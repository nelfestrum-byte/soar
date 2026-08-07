# Plan: web-agent-bridge

Spec: `docs/compose/specs/2026-08-07-web-agent-bridge-design.md`

- [x] `tests/misc/web_agent/test_server.py`: write failing tests first,
      against a fake CLI (a small Python script fixture invoked as the
      "wrapped CLI" — no dependency on the real `claude` binary):
  - `test_health_returns_ok_and_session_id_without_invoking_cli` — `GET
    /health` before any `/message` call returns `{"status": "ok",
    "session_id": <str>}` and the fake CLI is never invoked (assert no
    stdout marker file / call-count file was written).
  - `test_first_message_creates_session_and_uses_new_session_args` —
    `POST /message {"text": "hi"}` builds argv as `BASE_ARGS +
    NEW_SESSION_ARGS.format(session_id=...) + [prompt or nothing]`
    depending on `PROMPT_MODE`; response has `session_id`, `stdout`,
    `stderr`, `returncode`, `duration_s`.
  - `test_second_message_reuses_session_id_and_uses_resume_args` — a
    second `/message` call reuses the same `session_id` as the first
    response and argv is built from `RESUME_SESSION_ARGS` instead.
  - `test_prompt_mode_stdin_writes_text_to_subprocess_stdin` — with
    `PROMPT_MODE = "stdin"`, prompt text goes to the subprocess's stdin,
    not argv.
  - `test_prompt_mode_arg_appends_text_as_trailing_argv` — with
    `PROMPT_MODE = "arg"`, prompt text is the trailing positional argv
    entry.
  - `test_nonzero_cli_returncode_is_still_http_200` — fake CLI exits 1;
    `/message` still returns HTTP 200 with `returncode: 1` in the body.
  - `test_malformed_request_body_returns_non_200` — missing/invalid
    `text` key in the JSON body → non-200, no subprocess invoked.
  - `test_subprocess_timeout_returns_non_200` — fake CLI sleeps past a
    short configured timeout → non-200, no crash.
  - `test_missing_cli_binary_returns_non_200` — `BASE_ARGS[0]` points at a
    nonexistent path → non-200 (`FileNotFoundError` caught), not a
    500-with-traceback or hang.
  - `test_transcript_log_appends_readable_block_per_exchange` — after one
    `/message` call, the configured log file contains a block with the
    request text, stdout, stderr, returncode, and timing; a second call
    appends rather than overwrites.
  - `test_requests_are_served_strictly_sequentially` — start two
    `/message` calls against a fake CLI that blocks until a marker file
    appears; assert the second subprocess isn't launched until the first
    one's response has been written (proves `HTTPServer`, not
    `ThreadingHTTPServer`, is in use) — e.g. drive the server in a thread,
    fire two client requests concurrently, and check invocation
    timestamps/order recorded by the fake CLI don't overlap.
      Settings for the tests point at the fixture CLI script and a
      `tmp_path` log file — no real `claude` invocation anywhere in this
      suite.
- [x] Run the new test file, confirm it fails (no `server.py` yet).
- [x] `misc/web-agent/settings.example.py`: committed template — stdlib
      only, placeholder `CLI_PATH`, `BASE_ARGS`, `NEW_SESSION_ARGS`,
      `RESUME_SESSION_ARGS` (each a list template with a `{session_id}`
      placeholder), `PROMPT_MODE` (`"arg"` or `"stdin"`), `CWD`, `HOST`
      (default `127.0.0.1`), `PORT`, `LOG_FILE`, `TIMEOUT_S`.
- [x] `misc/web-agent/server.py`: stdlib-only implementation per [S3]:
  - Load settings from sibling `settings.py` by default, `--settings
    <path>` CLI flag (via `argparse`) to override, loaded with
    `importlib.util.spec_from_file_location`.
  - One in-memory `session_id` (created via `uuid` on first `/message`
    call), no persistence across restarts.
  - `BaseHTTPRequestHandler` subclass on a single-threaded
    `http.server.HTTPServer` (explicitly not `ThreadingHTTPServer`) —
    request handling naturally serializes CLI turns.
  - `GET /health` → `{"status": "ok", "session_id": session_id or null}`,
    no subprocess call.
  - `POST /message` → parse JSON body, validate `text` key present
    (else non-200); build argv from `BASE_ARGS` + session-args template
    (`NEW_SESSION_ARGS` if no session yet, else `RESUME_SESSION_ARGS`,
    `.format(session_id=...)`) + prompt per `PROMPT_MODE`; run via
    `subprocess.run(..., cwd=CWD, capture_output=True, text=True,
    timeout=TIMEOUT_S, input=prompt if stdin mode else None)`; catch
    `subprocess.TimeoutExpired` and `FileNotFoundError` → non-200; on
    success (any returncode) → HTTP 200 with `{"session_id", "stdout",
    "stderr", "returncode", "duration_s"}`; append a transcript block to
    `LOG_FILE` (request text, stdout, stderr, returncode, timing,
    timestamp) on every completed exchange.
  - `if __name__ == "__main__":` entry point starting the server on
    `HOST:PORT` from settings.
- [x] Run `tests/misc/web_agent/test_server.py`, confirm all pass.
- [x] `.gitignore`: add `misc/web-agent/settings.py`.
- [ ] Manual smoke check (not a substitute for the automated suite, but
      confirms the real `claude --bare` path end-to-end): write a local
      `misc/web-agent/settings.py` wrapping `claude --bare
      --allowedTools ...`, start `server.py`, exercise `/health` then two
      `/message` turns with `curl` to confirm session continuity and log
      output, then delete/leave the gitignored local settings file.
      **Skipped** — requires an interactive terminal session against the
      real `claude` binary, not something a background agent can
      meaningfully do. Left for the calling session to run.
- [x] Run full `tests/` suite touched by this change (at minimum
      `tests/misc/`) to confirm no regressions.
- [x] Report: `docs/compose/reports/web-agent-bridge.md`.
