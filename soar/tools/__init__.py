from soar.tools.http_client import HttpClient

# Default: pure logging-proxy (no cache backend). soar/runner.py reassigns
# this singleton at process start once SOAR_CONFIG's http_client section is
# read, so actions can always `from soar.tools import http_client` and call
# `await http_client.get_json(...)` without wiring anything themselves.
http_client = HttpClient()
