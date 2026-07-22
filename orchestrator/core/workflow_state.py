from pathlib import Path

import yaml


def _state_path(config) -> Path:
    return Path(config.soar.workflows_dir).parent / "orchestrator_state.yaml"


def load_state(config) -> dict:
    path = _state_path(config)
    if not path.exists():
        return {}
    with open(path) as f:
        return (yaml.safe_load(f) or {}).get("workflows", {})


def parse_enabled(value) -> bool:
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    if isinstance(value, str):
        return value == "enabled"
    return bool(value)


def parse_token(value) -> str | None:
    return value.get("token") if isinstance(value, dict) else None


def save_state(config, metas: list) -> None:
    path = _state_path(config)
    state = {"workflows": {}}
    for meta in metas:
        entry = {"enabled": meta.enabled}
        if meta.type == "webhook" and getattr(meta, "token", None):
            entry["token"] = meta.token
        state["workflows"][meta.name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(state, f)


def remove_from_state(config, name: str) -> None:
    path = _state_path(config)
    if not path.exists():
        return
    with open(path) as f:
        state = yaml.safe_load(f) or {}
    workflows = state.get("workflows", {})
    if name in workflows:
        del workflows[name]
        state["workflows"] = workflows
        with open(path, "w") as f:
            yaml.dump(state, f)
