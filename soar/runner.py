import importlib
import json
import os
import sys

import yaml

import soar.tools as tools
from soar.actions import actions
from soar.audit_hook import flush as flush_audit_hook
from soar.audit_hook import install as install_audit_hook
from soar.connectors import connectors
from soar.logger import setup_logging
from soar.tools._cache import CacheBackend, InMemoryCache, RedisCache
from soar.tools.http_client import CachingHttpClient, LoggingHttpClient
from soar.workflows import workflows

# `soar.tools.__init__` rebinds the name `http_client` in the package
# namespace to a LoggingHttpClient instance (tools.http_client below), so
# `import soar.tools.http_client as http_client_module` (an attribute-chain
# lookup) would resolve to that instance, not the submodule —
# importlib.import_module goes through sys.modules instead, same pitfall
# documented in tests/soar/tools/test_new_client.py.
http_client_module = importlib.import_module("soar.tools.http_client")

setup_logging(level="INFO")
if __name__ == "__main__":
    # sys.addaudithook — необратим на весь процесс (нет sys.removeaudithook).
    # Гейт на __main__, а не голый вызов на уровне модуля: real subprocess
    # entrypoint (`python -m soar.runner`) всегда исполняется как __main__,
    # так что хук по-прежнему ставится до любого init() ниже для настоящего
    # запуска воркфлоу. Прямой `from soar import runner` (юнит-тесты
    # soar/runner.py в одном процессе с остальным pytest-сьютом, см.
    # tests/soar/test_runner.py) не ставит __name__ в "__main__" — без этого
    # гейта хук бы включался один раз на весь pytest-процесс и после этого
    # блокировал бы socket.connect на 127.0.0.1/loopback во всех остальных
    # тестах (Redis/scheduler/worker/http_client), которые уже полагаются на
    # реальные localhost-сокеты в своих фикстурах.
    install_audit_hook()  # до любого init() ниже — видит всё, что делает контент

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


def _build_cache(http_cfg: dict, queue_cfg: dict) -> CacheBackend | None:
    cache_backend = http_cfg.get("cache_backend", "memory")
    if cache_backend == "memory":
        return InMemoryCache()
    elif cache_backend == "redis":
        redis_url = queue_cfg.get("redis_url", "")
        if not redis_url:
            raise ValueError(
                "http_client.cache_backend is 'redis' but queue.redis_url is empty"
            )
        return RedisCache(redis_url)
    elif cache_backend == "none":
        return None
    raise ValueError(f"Unknown http_client.cache_backend: {cache_backend!r}")


def _build_http_client(config: dict) -> LoggingHttpClient:
    http_cfg = config.get("http_client", {})
    cache = _build_cache(http_cfg, config.get("queue", {}))
    default_ttl = http_cfg.get("default_ttl", 3600)
    domain_ttl = http_cfg.get("domain_ttl", {})
    # Fills soar/tools/http_client.py's module-level _shared_* globals so
    # new_client() (called from a connector's _connect_impl for verify_ssl=
    # False/persistent-cookie-jar cases) shares the same cache/ttl config as
    # the tools.http_client singleton built below, instead of each building
    # (and connecting) its own CacheBackend.
    http_client_module._shared_cache = cache
    http_client_module._shared_default_ttl = default_ttl
    http_client_module._shared_domain_ttl = domain_ttl
    if cache is None:
        return LoggingHttpClient()
    return CachingHttpClient(cache=cache, default_ttl=default_ttl, domain_ttl=domain_ttl)


# Must run before workflows.init()/connectors.init()/actions.init() below:
# those import all user workflow/action/connector modules, and any such
# module doing a top-level `from soar.tools import http_client` binds to
# whatever soar.tools.http_client already is at that moment (see
# docs/compose/specs/2026-07-28-http-client-init-order-design.md [S1]).
tools.http_client = _build_http_client(config)

connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))
workflows.init(external_dir=external_dirs.get("workflows"))


def main():
    import traceback as tb

    workflow_name = os.environ.get("SOAR_WORKFLOW_NAME", "")
    context_str = os.environ.get("SOAR_CONTEXT", "{}")

    try:
        context = json.loads(context_str)
    except json.JSONDecodeError:
        context = {}

    from soar.runtime_state import set_dry_run

    set_dry_run(bool(context.get("dry_run", False)))

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
    finally:
        flush_audit_hook()

    print(json.dumps(output))

    if not output["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
