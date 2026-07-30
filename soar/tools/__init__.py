from soar.tools.http_client import HttpClient, SyncHttpClient
from soar.tools.watermark import SeenStore, WatermarkStore, seen_store, watermark_store

# Default: pure logging-proxy (no cache backend). soar/runner.py reassigns
# this singleton at process start once SOAR_CONFIG's http_client section is
# read, so actions can always `from soar.tools import http_client` and call
# `await http_client.get_json(...)` without wiring anything themselves.
http_client = HttpClient()

# Sync twin of http_client, for synchronous connector code (see
# soar/tools/http_client.py::SyncHttpClient). Reassigned alongside
# http_client in soar/runner.py, from the same http_client: config section.
http_client_sync = SyncHttpClient()

# Explicit public surface (E5) — GET /tools reads this via AST
# (orchestrator/core/introspect.py::_public_names), not a directory glob.
# Internal mechanics (CacheBackend/InMemoryCache/RedisCache in
# http_client.py) stay unexported on purpose. Classes are exported alongside
# the ready-made factories/singletons for tests and non-standard paths.
__all__ = [
    "http_client",
    "http_client_sync",
    "WatermarkStore",
    "SeenStore",
    "watermark_store",
    "seen_store",
]
