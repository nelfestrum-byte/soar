import importlib.metadata
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from orchestrator.auth.dependencies import require_role
from soar.runtime_contract import CONTRACT, RUNTIME_VERSION

router = APIRouter(prefix="/runtime", tags=["runtime"])
_RO = ("viewer", "analyst", "service", "admin", "agent")


def _content_venv_root(content_python: str) -> Path:
    # .../content-venv/bin/python -> .../content-venv
    return Path(content_python).resolve().parent.parent


def _site_packages(venv_root: Path) -> list[str]:
    lib = venv_root / "lib"
    if not lib.is_dir():
        return []
    return [str(p) for p in lib.glob("python3.*/site-packages") if p.is_dir()]


def _python_version(venv_root: Path) -> str | None:
    cfg = venv_root / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text().splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip()
    return None


def _top_level_names(dist: importlib.metadata.Distribution) -> list[str]:
    raw = dist.read_text("top_level.txt")
    if raw:
        return [n for n in raw.splitlines() if n]
    return [dist.metadata["Name"].replace("-", "_")]


@router.get("", dependencies=[Depends(require_role(*_RO))])
async def get_runtime(request: Request):
    content_python = request.app.state.content_python
    venv_root = _content_venv_root(content_python)
    paths = _site_packages(venv_root)
    dists = list(importlib.metadata.distributions(path=paths)) if paths else []
    by_name = {d.metadata["Name"].lower(): d for d in dists}

    guaranteed = []
    for dist_key, entry in CONTRACT.items():
        d = by_name.get(dist_key.lower())
        if d is None:
            continue  # объявлено контрактом, но не установлено — расхождение сборки, не 500
        guaranteed.append({
            "distribution": d.metadata["Name"],
            "version": d.version,
            "import_names": entry["import_names"],
            "kind": entry["kind"],
        })

    declared = {k.lower() for k in CONTRACT}
    present_not_guaranteed = [
        {"distribution": d.metadata["Name"], "version": d.version, "import_names": _top_level_names(d)}
        for d in dists if d.metadata["Name"].lower() not in declared
    ]

    return {
        "runtime_version": RUNTIME_VERSION,
        "python_version": _python_version(venv_root),
        "guaranteed": sorted(guaranteed, key=lambda x: x["distribution"]),
        "present_not_guaranteed": sorted(present_not_guaranteed, key=lambda x: x["distribution"]),
    }
