"""Template settings for misc/web-agent/server.py.

Copy this file to `settings.py` (gitignored) next to it and fill in real
values for your deployment. `server.py` never reads `settings.example.py`
directly — it loads the sibling `settings.py` by default, or whatever path
is passed via `--settings`.

Nothing in server.py is specific to any one CLI: genericity comes entirely
from the values below. `CLI_PATH` is just a convenience constant used to
build `BASE_ARGS` in this file — server.py only ever reads `BASE_ARGS`.
"""

CLI_PATH = "/usr/local/bin/claude"

# Full base command line, executable first. `--output-format stream-json`
# (plus `--verbose`, which the CLI requires alongside it) is what lets
# server.py append output to the transcript log as it's produced instead of
# only once the whole turn finishes — turns can run for the better part of
# an hour on real work, and a synchronous "one block at the end" log is no
# visibility at all until it's over. Anything the CLI needs on every
# invocation (auth, permission mode, isolation/tool flags) belongs here too,
# not in NEW_SESSION_ARGS/RESUME_SESSION_ARGS.
BASE_ARGS = [
    CLI_PATH,
    "-p",
    "--output-format", "stream-json",
    "--verbose",
    "--permission-mode", "bypassPermissions",
]

# Appended to BASE_ARGS on the first turn of a conversation (no session yet).
# Must contain the literal placeholder "{session_id}" wherever the CLI
# expects a session identifier.
NEW_SESSION_ARGS = ["--session-id", "{session_id}"]

# Appended to BASE_ARGS on every subsequent turn of the same conversation.
RESUME_SESSION_ARGS = ["--resume", "{session_id}"]

# "arg": prompt text is appended as the trailing positional argv entry.
# "stdin": prompt text is written to the subprocess's stdin instead.
PROMPT_MODE = "arg"

# Working directory the CLI subprocess is launched in.
CWD = "/path/to/incident/workdir"

HOST = "127.0.0.1"
PORT = 8787

# Local transcript of every exchange, appended to incrementally as the
# subprocess streams output (not just once at the end).
LOG_FILE = "/path/to/incident/workdir/web-agent-bridge.log"

# Outer safety net, not a routine limit: a turn running longer than this is
# killed automatically (server.py still has the full transcript up to the
# kill point either way — see Turn/_run_turn). Real multi-step sysadmin/
# incident-response work can run for the better part of an hour; this is a
# backstop against a genuinely stuck turn, not a normal-completion budget.
TIMEOUT_S = 14400
