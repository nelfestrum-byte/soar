import json
import os
import sys

import yaml

import soar.tools as tools
from soar.actions import actions
from soar.connectors import connectors
from soar.logger import setup_logging
from soar.tools.http_client import HttpClient, InMemoryCache, RedisCache
from soar.workflows import workflows

setup_logging(level="INFO")

config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
external_dirs = {}
config: dict = {}
try:
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    soar_config = config.get("soar", {})
    external_dirs = {
        "workflows": soar_config.get("workflows_dir"),
        "connectors": soar_config.get("connectors_dir"),
        "actions": soar_config.get("actions_dir"),
    }
except FileNotFoundError:
    import sys
    print(f"Warning: Config file not found at {config_path}", file=sys.stderr)
except Exception as e:
    import sys
    print(f"Warning: Failed to load config from {config_path}: {e}", file=sys.stderr)

workflows.init(external_dir=external_dirs.get("workflows"))
connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))


def _build_http_client(config: dict) -> HttpClient:
    http_cfg = config.get("http_client", {})
    cache_backend = http_cfg.get("cache_backend", "memory")
    default_ttl = http_cfg.get("default_ttl", 3600)
    domain_ttl = http_cfg.get("domain_ttl", {})

    if cache_backend == "memory":
        cache = InMemoryCache()
    elif cache_backend == "redis":
        redis_url = config.get("queue", {}).get("redis_url", "")
        if not redis_url:
            raise ValueError(
                "http_client.cache_backend is 'redis' but queue.redis_url is empty"
            )
        cache = RedisCache(redis_url)
    elif cache_backend == "none":
        cache = None
    else:
        raise ValueError(f"Unknown http_client.cache_backend: {cache_backend!r}")

    return HttpClient(cache=cache, default_ttl=default_ttl, domain_ttl=domain_ttl)


tools.http_client = _build_http_client(config)


def main():
    import traceback as tb

    workflow_name = os.environ.get("SOAR_WORKFLOW_NAME", "")
    context_str = os.environ.get("SOAR_CONTEXT", "{}")

    try:
        context = json.loads(context_str)
    except json.JSONDecodeError:
        context = {}

    try:
        result = workflows.execute(workflow_name, context)
        output = {
            "success": result.success,
            "workflow_name": result.workflow_name,
            "duration_seconds": result.duration_seconds,
            "data": result.data,
        }
        if result.error:
            output["error"] = result.traceback or str(result.error)
    except Exception:
        output = {
            "success": False,
            "workflow_name": workflow_name,
            "duration_seconds": None,
            "data": None,
            "error": tb.format_exc(),
        }

    print(json.dumps(output))

    if not output["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
