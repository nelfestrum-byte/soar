"""Fixture "CLI" used by tests/misc/web_agent/test_server.py.

Stands in for a real headless CLI (e.g. ``claude --bare``) so the bridge's
test suite never has to invoke the real binary. Controlled entirely through
environment variables so tests can drive its behaviour without editing this
file:

- ``FAKE_CLI_CALLS_LOG``: if set, append a JSON line at invocation start and
  another at invocation end (argv, stdin, timestamp) — used to prove
  requests are served strictly sequentially.
- ``FAKE_CLI_SLEEP``: seconds to sleep before exiting (simulates a slow
  turn / triggers a timeout).
- ``FAKE_CLI_EXIT_CODE``: process exit code (default ``0``).

Always echoes argv and stdin back as a JSON object on stdout, and writes a
fixed marker line to stderr, so tests can assert exactly what the bridge
passed through.
"""

import json
import os
import sys
import time


def main() -> None:
    argv = sys.argv[1:]
    stdin_data = sys.stdin.read()

    calls_log = os.environ.get("FAKE_CLI_CALLS_LOG")
    if calls_log:
        with open(calls_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "start", "argv": argv, "t": time.time()}) + "\n")

    sleep_s = os.environ.get("FAKE_CLI_SLEEP")
    if sleep_s:
        time.sleep(float(sleep_s))

    if calls_log:
        with open(calls_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "end", "argv": argv, "t": time.time()}) + "\n")

    print(json.dumps({"argv": argv, "stdin": stdin_data}))
    print("fake-cli-stderr-marker", file=sys.stderr)

    sys.exit(int(os.environ.get("FAKE_CLI_EXIT_CODE", "0")))


if __name__ == "__main__":
    main()
