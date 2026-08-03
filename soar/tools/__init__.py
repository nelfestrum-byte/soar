from soar.tools.http_client import CachingHttpClient, LoggingHttpClient, new_client
from soar.tools.watermark import SeenStore, WatermarkStore, seen_store, watermark_store

# Default: pure logging-proxy (no cache backend). soar/runner.py reassigns
# this singleton at process start once SOAR_CONFIG's http_client section is
# read, so actions can always `from soar.tools import http_client` and call
# `http_client.get(...)`/`.post(...)` without wiring anything themselves.
http_client = LoggingHttpClient()

# Explicit public surface — orchestrator/core/introspect.py::parse_tool_registry
# reads this literal dict via AST (never imports soar/tools/) to build
# GET /tools. `kind` drives how each name is introspected:
#   - "class": parse_classes(module) by name as-is
#   - "instance": parse_classes(module) resolves the class named in "of";
#     the card is served under the public instance name, plus "instance_of"
#   - "factory": parse_functions(module) by name
# Internal mechanics (CacheBackend/InMemoryCache/RedisCache in _cache.py,
# _validate_external_url/_is_private_ip/_log_safe_url in _net.py) stay out
# of the registry on purpose — `_`-prefixed modules are never globbed by
# GET /tools (orchestrator/api/tools.py).
TOOL_REGISTRY = {
    "http_client":       {"kind": "instance", "of": "LoggingHttpClient", "module": "http_client"},
    "LoggingHttpClient": {"kind": "class", "module": "http_client"},
    "CachingHttpClient": {"kind": "class", "module": "http_client"},
    "new_client":        {"kind": "factory", "module": "http_client"},
    "WatermarkStore":    {"kind": "class", "module": "watermark"},
    "SeenStore":         {"kind": "class", "module": "watermark"},
    "watermark_store":   {"kind": "factory", "module": "watermark"},
    "seen_store":        {"kind": "factory", "module": "watermark"},
}

__all__ = list(TOOL_REGISTRY)
