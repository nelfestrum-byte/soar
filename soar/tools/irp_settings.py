"""Settings of the IRP integration workflows.

Read from the orchestrator config.yaml (section ``irp``) — the same file the
subprocess runner already exposes via SOAR_CONFIG, so workflows need no extra
wiring. Everything is configurable, nothing hardcoded (project rule); defaults
match the stage deploy layout (/app/data volume survives restarts).
"""

import os

import yaml

from soar.logger import get_logger

_log = get_logger("tools.irp_settings")

DEFAULTS = {
    # master switch: without an explicit irp.enabled=true the scheduled
    # workflows no-op instead of failing every cycle on a vanilla deploy
    "enabled": False,
    # shadow mode is the safe default until cutover (contract §4.4)
    "shadow": True,
    # connector instance names in the connector registry
    "connector": "irp_main",
    "elastic_connector": "elastic_main",
    # ES source of SIEM alerts
    "alerts_index": ".internal.alerts-*",
    # durable state (must live on a docker volume)
    "watermark_path": "/app/data/irp/watermark.json",
    "seen_path": "/app/data/irp/seen.json",
    "seen_ttl": 86400,
    # triage policies (SOC Core settings API, assumption Д-3)
    "policy_endpoint": "/api/v2/settings/triage",
    "policy_cache_path": "/app/data/irp/policy_cache.json",
    "policy_ttl": 60,
    # triage windows (contract §4.3)
    "time_window_minutes": 10,
    "overlap_minutes": 5,
    "fetch_size": 1000,
    # response dispatch (plan Task 3)
    "orchestrator_url": "http://127.0.0.1:8000",
    "response_workflow": "respond_basic",
    "min_response_severity": 3,
}


def load_irp_settings(config_path: str | None = None) -> dict:
    path = config_path or os.environ.get("SOAR_CONFIG", "config.yaml")
    settings = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        irp = config.get("irp") or {}
        if not isinstance(irp, dict):
            irp = {}
        settings.update(irp)
    except FileNotFoundError:
        _log.warning(f"config {path} not found, IRP integration disabled")
    except Exception as e:
        _log.warning(f"failed to load IRP settings from {path}: {e}")
    return settings
