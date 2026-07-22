"""Instance bootstrap: generates .env secrets and renders config.yaml from
config.yaml.template. Two distinct substitution mechanisms on purpose:
docker compose expands ${VAR} in docker-compose.yml straight from .env, but
orchestrator/config.py does a plain yaml.safe_load with no env expansion —
so config.yaml.template has to be rendered to a real config.yaml here,
with literal secret values, not left as ${VAR} for compose to resolve.
"""

import secrets
from pathlib import Path
from string import Template

from .paths import read_version


def generate_secrets() -> dict[str, str]:
    return {
        "AUTH_SECRET_KEY": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "SOAR_WEBHOOK_TOKEN": secrets.token_hex(16),
    }


def render_template(text: str, values: dict[str, str]) -> str:
    return Template(text).safe_substitute(values)


def init_instance(directory: Path, force: bool = False) -> None:
    template_path = directory / "config.yaml.template"
    if not template_path.exists():
        raise FileNotFoundError(f"config.yaml.template not found in {directory}")

    env_path = directory / ".env"
    if env_path.exists() and not force:
        raise FileExistsError(f"{env_path} already exists — pass force=True to regenerate secrets")

    version = read_version(directory)
    values = generate_secrets()
    values["SOAR_VERSION"] = version

    env_text = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    env_path.write_text(env_text)

    config_text = render_template(template_path.read_text(), values)
    (directory / "config.yaml").write_text(config_text)


def update_version(directory: Path, version: str) -> None:
    """Bumps SOAR_VERSION in an existing .env without touching secrets —
    used by `soarctl install` on upgrade, where regenerating AUTH_SECRET_KEY/
    POSTGRES_PASSWORD would lock the instance out of its own database.
    """
    env_path = directory / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"{env_path} not found — run `soarctl init` first")

    lines = env_path.read_text().splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("SOAR_VERSION="):
            lines[i] = f"SOAR_VERSION={version}"
            replaced = True
            break
    if not replaced:
        lines.append(f"SOAR_VERSION={version}")

    env_path.write_text("\n".join(lines) + "\n")
