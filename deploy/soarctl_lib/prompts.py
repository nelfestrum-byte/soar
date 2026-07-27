"""Interactive config prompts for `soarctl init --interactive` — kept to one
question (UI CORS origins) on purpose, see
docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md [S2]. The
validation itself (`_valid_origin`) is a pure function so it's tested without
touching `input()`; `prompt_cors_origins` is a thin re-prompt loop around it,
same split as `getpass` in orchestrator/auth/cli.py.
"""

from urllib.parse import urlparse


def _valid_origin(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def prompt_cors_origins(input_fn=input) -> list[str]:
    prompt = "UI origin(s) for CORS, comma-separated (e.g. https://soar.example.com): "
    while True:
        raw = input_fn(prompt)
        origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
        if origins and all(_valid_origin(origin) for origin in origins):
            return origins
        prompt = "Invalid input — enter one or more http(s):// URLs, comma-separated: "
