# Generic CLI-to-HTTP bridge for blind agent-to-agent testing

## [S1] Problem

We're running a blind integration test of the SOAR project on a live stand
(SecurityOnion 3.2 + a Debian 13 VM running the deployed orchestrator): one
agent session acts as SOAR admin (deploys the stand, has full repo context),
a second, independent agent session acts as an analyst working an incident
(TrueConf credential-stuffing case) purely against the deployed API — it must
not see this repository or its `CLAUDE.md`/`AGENTS.md` instructions, or the
test isn't blind.

Both sessions need to exchange messages autonomously, without a human
relaying text between two terminal windows. The built-in `SendMessage` tool
only reaches agents spawned as "teammates" within the same session's own
agent tree ("to": teammate name or "main") — it has no way to address an
independently-launched session, so it can't bridge the admin and analyst here.

Separately, spawning the analyst as a subagent of the admin session (making
`SendMessage` work) was considered and rejected: a subagent inherits the
admin session's fixed primary working directory, and this repo's
`CLAUDE.md`/`AGENTS.md` context is injected based on that directory
regardless of the subagent's own prompt or cwd. There is no parameter on the
`Agent` tool to relocate a subagent's primary working directory, so any
subagent spawned this way carries at least partial project context —
"best-effort blindness" via prompt discipline, not a structural guarantee.

The installed `claude` CLI (v2.1.153) already supports true headless
isolation when invoked as a plain subprocess: `--bare` skips
`CLAUDE.md`/hooks/plugin-sync/auto-memory discovery entirely; `--tools`/
`--allowedTools` structurally remove tools from the session rather than just
gating permission prompts; the subprocess's own `cwd` controls what's on
disk; `--session-id`/`--resume` carry a conversation across separate
invocations. What's missing is a way to reach that subprocess over the
network from another independent session, and a place to persist a
human-readable transcript of the exchange.

## [S2] Solution

A small, CLI-agnostic HTTP wrapper: one process spawns and re-invokes a
configured headless CLI as a subprocess per request, exposing it as
`POST /message`. Two independent sessions (or more generally, any two
processes that can reach each other over HTTP) then talk through this
bridge without either one needing tool-level access to the other.

Genericity comes entirely from the settings file, not from the module: CLI
executable path, static launch args, working directory, how the prompt text
is delivered to the CLI (trailing positional argument vs stdin), and — the
key abstraction point — two argument templates, `NEW_SESSION_ARGS` and
`RESUME_SESSION_ARGS`, each containing a `{session_id}` placeholder. Any CLI
that exposes "start a new session" / "resume session N" via flags (as
`claude` does with `--session-id`/`--resume`) can be wrapped by filling in
these two templates; a CLI with no session concept leaves both empty and
every call is stateless. The module itself never hardcodes anything specific
to `claude` — it only knows "argv in, stdout/stderr/returncode out."

The bridge holds exactly one conversation per running process (one
in-memory session id, created on first request, no persistence across
restarts). Wrapping a second CLI, or running a second independent
conversation with the same CLI, means starting a second instance with its
own settings file and port — deliberately, rather than adding
multi-session bookkeeping to the module (see Non-goals).

Requests are served strictly one at a time (a single-threaded
`http.server.HTTPServer`, not the threading variant): CLI turns must stay
sequential, since two interleaved subprocess invocations against the same
`--resume <id>` would race and corrupt session state. This is a deliberate
property of the design, not a missing feature.

Every exchange (request text, response stdout/stderr, return code, timing)
is appended as a readable block to a local text log — the transcript is the
audit trail of the blind test, independent of whatever logging the wrapped
CLI itself produces.

## [S3] Architecture

```
misc/web-agent/
├── server.py              # NEW: HTTP server + subprocess bridge, stdlib only
├── settings.example.py    # NEW: committed template, placeholder values
└── settings.py            # NEW (gitignored): real local config per deployment
.gitignore                 # MODIFY: ignore misc/web-agent/settings.py
tests/misc/web_agent/
└── test_server.py         # NEW
```

`server.py` has no dependency beyond the standard library
(`http.server`, `json`, `subprocess`, `uuid`, `time`, `pathlib`, `argparse`,
`importlib.util`) — matching the existing precedent in
`deploy/soarctl_lib/status.py` of using stdlib `urllib` rather than adding an
HTTP dependency for a small, single-purpose utility script outside the main
product packages.

Settings are loaded from the sibling `settings.py` by default; an optional
`--settings <path>` flag on `server.py` loads an alternate file instead, so
multiple bridge instances (different CLI, different incident directory,
different port) can run from independently-maintained config files without
editing the checked-in module.

Endpoints:

- `POST /message` — body `{"text": "..."}`. Runs exactly one CLI turn
  (constructing argv from `BASE_ARGS` + the appropriate session-args
  template + the prompt, per `PROMPT_MODE`), returns
  `{"session_id", "stdout", "stderr", "returncode", "duration_s"}`. HTTP 200
  whenever the subprocess actually completed, including a nonzero CLI
  returncode (that's a completed exchange the caller needs to see, not a
  transport failure); non-200 is reserved for a malformed request body, a
  subprocess timeout, or the configured CLI binary not being found.
- `GET /health` — `{"status": "ok", "session_id": ...}` with no CLI
  invocation, so a caller can confirm the bridge is up before spending a CLI
  turn on it. Mirrors the existing liveness-check shape in
  `deploy/soarctl_lib/status.py`.

`misc/` is new at the repo root — this is the first thing under it. It sits
outside `soar/`/`orchestrator/`/`deploy/` on purpose: it is test-harness
tooling for this blind-testing exercise, not part of the shipped product, so
it doesn't touch `soar/config.py`, the orchestrator's connector/workflow
registries, or any deploy bundle.

## [S4] Non-goals

- No authentication/token on the HTTP endpoints — binds `127.0.0.1` by
  default (settings-configurable); this is a throwaway test-harness bridge
  for a controlled lab stand, not a hardened service.
- No multi-session / concurrent-conversation support in one process. One
  bridge instance = one ongoing CLI conversation, by design (see [S2]).
- No persistence of the session id across a bridge-process restart — a
  restart starts a fresh CLI session; this is a known, accepted limitation
  for a test harness, not something the module works around.
- No parsing/interpretation of the wrapped CLI's stdout (e.g. no
  `claude`-specific `--output-format json` unwrapping). The bridge passes
  stdout/stderr through verbatim in its own envelope — keeping it CLI-agnostic
  is more valuable here than convenience for one specific CLI.

## [S5] Success Criteria

- [ ] `misc/web-agent/server.py` wraps an arbitrary headless CLI (configured
      entirely via `settings.py`, no `claude`-specific code in the module) and
      serves `POST /message` / `GET /health` over plain HTTP.
- [ ] Two independent local processes (e.g. this bridge fronting `claude
      --bare` in one incident directory, and a plain `curl`/script from
      another session) can hold a multi-turn conversation through the bridge
      with no human copy-pasting text between them.
- [ ] Every exchange is appended as a readable block to a local text log file.
- [ ] `settings.example.py` is committed with placeholder values;
      `misc/web-agent/settings.py` is gitignored.
