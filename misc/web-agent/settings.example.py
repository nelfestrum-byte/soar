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

# Full base command line, executable first. Anything the CLI needs on every
# invocation (flags that structurally restrict the session, e.g. isolation
# / tool allowlists) belongs here, not in NEW_SESSION_ARGS/RESUME_SESSION_ARGS.
BASE_ARGS = [
    CLI_PATH,
    "--bare",
    "--allowedTools",
    "",
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

# Local transcript of every exchange (readable text blocks, appended).
LOG_FILE = "/path/to/incident/workdir/web-agent-bridge.log"

# Seconds to wait for one CLI turn before giving up (subprocess.run timeout).
TIMEOUT_S = 300
