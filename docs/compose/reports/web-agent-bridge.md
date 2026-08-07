# Report: generic CLI-to-HTTP bridge for blind agent-to-agent testing

Spec: `docs/compose/specs/2026-08-07-web-agent-bridge-design.md`
Plan: `docs/compose/plans/2026-08-07-web-agent-bridge.md`

## Summary

Built `misc/web-agent/server.py`, a stdlib-only HTTP wrapper that spawns a
configured headless CLI as a subprocess per request and exposes it as
`POST /message` / `GET /health`. Two independent local processes can now
hold a multi-turn conversation with a wrapped CLI over plain HTTP, with no
human relaying text between terminal windows.

Genericity comes entirely from `settings.py` (loaded via
`importlib.util.spec_from_file_location`, sibling file by default,
`--settings <path>` to override): `BASE_ARGS`, `NEW_SESSION_ARGS`/
`RESUME_SESSION_ARGS` (each with a `{session_id}` placeholder),
`PROMPT_MODE` (`"arg"`/`"stdin"`), `CWD`, `HOST`, `PORT`, `LOG_FILE`,
`TIMEOUT_S`. `server.py` itself has no `claude`-specific code anywhere —
verified by grep, nothing in the module references `claude`.

The server holds exactly one in-memory `session_id` per process (created on
first `/message` call, no persistence across restarts) and runs on a
single-threaded `http.server.HTTPServer` (explicitly not
`ThreadingHTTPServer`), so CLI turns are strictly serialized — two
concurrent `--resume <id>`-style invocations against the same session
cannot race.

## Changes

- `misc/web-agent/server.py` (new) — `load_settings()`, `BridgeState`,
  `make_handler_class()` (builds a `BaseHTTPRequestHandler` closing over a
  `BridgeState`), `build_server()`, `main()`. `POST /message` validates the
  JSON body has a string `text` field (else HTTP 400, no subprocess
  invoked); builds argv from `BASE_ARGS` + the new/resume session-args
  template + prompt (per `PROMPT_MODE`); runs via `subprocess.run(...,
  timeout=TIMEOUT_S)`; catches `subprocess.TimeoutExpired` (→ 504) and
  `FileNotFoundError` (→ 502); any completed run (including nonzero
  returncode) → HTTP 200 with `{"session_id", "stdout", "stderr",
  "returncode", "duration_s"}`. When `PROMPT_MODE == "stdin"`, prompt text
  is passed via `subprocess.run(..., input=text)`; when `"arg"`, the
  subprocess's stdin is explicitly set to `subprocess.DEVNULL` (not left as
  inherited) so the wrapped CLI never blocks on an unexpected read from the
  bridge process's own stdin. Every completed exchange appends a readable
  block (timestamp, session id, duration, returncode, request text,
  stdout, stderr) to `LOG_FILE`.
- `misc/web-agent/settings.example.py` (new) — committed template with
  placeholder `CLI_PATH`/`BASE_ARGS`/`NEW_SESSION_ARGS`/
  `RESUME_SESSION_ARGS`/`PROMPT_MODE`/`CWD`/`HOST`/`PORT`/`LOG_FILE`/
  `TIMEOUT_S`, documented inline.
- `.gitignore` — added `misc/web-agent/settings.py`.
- `tests/misc/web_agent/fake_cli.py` (new) — fixture "CLI" driven entirely
  by env vars (`FAKE_CLI_CALLS_LOG`, `FAKE_CLI_SLEEP`, `FAKE_CLI_EXIT_CODE`),
  echoes argv/stdin back as JSON on stdout, writes a fixed marker to
  stderr. Never the real `claude` binary.
- `tests/misc/web_agent/test_server.py` (new) — 11 tests, all from the
  plan's checklist (the plan's bullet list itself enumerates 11 cases,
  including the malformed-body test covering three sub-cases in one
  function). `server.py` is loaded via
  `importlib.util.spec_from_file_location` in the test file too, since
  `misc/web-agent` (hyphenated) isn't importable as a normal package.

## Testing

Confirmed the suite failed before `server.py` existed (collection error,
`FileNotFoundError` on the not-yet-created file) — genuine test-first per
the plan.

```
python -m pytest tests/misc/web_agent/test_server.py -v
11 passed in 7.92s
```

All 11: health-without-invoking-cli, first-message creates session +
`NEW_SESSION_ARGS`, second-message reuses session id + `RESUME_SESSION_ARGS`,
stdin prompt mode, arg prompt mode, nonzero CLI returncode still HTTP 200,
malformed body → non-200 (bad JSON / missing `text` / non-string `text`, and
the fake CLI's calls-log file is confirmed absent, i.e. never invoked),
subprocess timeout → non-200, missing CLI binary → non-200, transcript log
appends (not overwrites) per exchange, and strict sequential serialization
(two concurrent requests against a fake CLI that sleeps 0.4s each; asserted
via timestamps recorded by the fake CLI that the second subprocess's start
time is not before the first subprocess's end time).

Full suite:

```
python -m pytest tests/ -q
3 failed, 886 passed, 9 skipped, 21 warnings in 129.45s
```

The 3 failures are all in `tests/orchestrator/test_redis_integration.py`
and are a pre-existing environment limitation (no Redis server listening on
`localhost:6379` in this sandbox — confirmed via the traceback, a raw
connection-refused inside `redis.asyncio.connection`), unrelated to this
change. No regressions from the new module or test files.

## Deviations from the plan

- **Manual smoke check against real `claude --bare` — skipped**, per
  explicit instruction. That step needs an interactive terminal session
  (write a local `settings.py`, start `server.py`, drive it with `curl`
  against a live `claude` process) and isn't something a background agent
  can meaningfully do. The plan checkbox is marked unchecked with a note;
  `misc/web-agent/settings.py` was never created in this environment (only
  the committed `settings.example.py` exists), so there's nothing gitignored
  left behind to clean up. The calling session should run this step
  directly against the lab machine.
- Nothing else deviated from the spec or plan. Endpoint contracts, argv
  construction, error-code mapping (400 malformed / 502 binary-not-found /
  504 timeout / 200 for any completed subprocess run), and the
  single-threaded-server requirement all match [S2]/[S3] as written.

## Success criteria (spec S5)

- [x] `misc/web-agent/server.py` wraps an arbitrary headless CLI (settings-
      only configuration, no `claude`-specific code in the module) and
      serves `POST /message` / `GET /health` over plain HTTP.
- [x] Two independent local processes can hold a multi-turn conversation
      through the bridge with no human relaying text — demonstrated in the
      automated suite (fake CLI over real HTTP, session continuity across
      two `/message` calls); the real-`claude` end-to-end variant is the
      skipped manual step above.
- [x] Every exchange is appended as a readable block to a local text log
      file — `test_transcript_log_appends_readable_block_per_exchange`.
- [x] `settings.example.py` is committed with placeholder values;
      `misc/web-agent/settings.py` is gitignored.
