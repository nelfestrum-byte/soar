"""POST /connectors/pack/install — install a connector content-pack
(Phase 3, docs/compose/specs/2026-07-30-content-as-contentpack-design.md
[S7]). Separate file rather than added to connectors.py: connectors.py is
already ~750 lines covering a different concern (CRUD/history/diff of one
connector's code+config); this is bulk multi-connector installs against a
manifest+marker, closer in shape to transfer.py/runtime.py (also their own
files despite being small) than to anything already in connectors.py.

admin-only — same risk category as /transfer/import (external code
entering the instance), not the broader analyst/agent write access
individual connector edits get.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.audit import service as audit_service
from orchestrator.auth.dependencies import CurrentUser, require_role
from orchestrator.core import pack_install
from orchestrator.db.session import get_db
from soar.runtime_contract import CONTRACT, RUNTIME_VERSION

router = APIRouter(prefix="/connectors/pack", tags=["connectors"], dependencies=[Depends(require_role("admin"))])


@router.post("/install")
async def install_pack(
    request: Request, file: UploadFile,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()

    try:
        manifest = pack_install.read_manifest(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        pack_install.check_runtime_compat(manifest, RUNTIME_VERSION)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    missing = pack_install.check_dependencies(manifest, CONTRACT)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Pack declares imports not guaranteed by the runtime contract: {missing} — "
                "extending soar/runtime_contract.py::CONTRACT is a platform release, not something "
                "this install can do on its own"
            ),
        )

    config = request.app.state.config
    connectors_dir = config.soar.connectors_dir
    marker = pack_install.read_marker(connectors_dir)
    plan = pack_install.plan_install(manifest, marker, connectors_dir)

    conflicts = [c["name"] for c in plan["update"]]
    force = request.query_params.get("force", "false").lower() == "true"
    if conflicts and not force:
        return {
            "status": "conflicts",
            "conflicts": conflicts,
            "message": f"Found {len(conflicts)} connector(s) that would be updated. Send force=true to proceed.",
        }

    written = pack_install.apply_install(plan, content, connectors_dir, manifest)
    skip_modified = [c["name"] for c in plan["skip_modified"]]

    await audit_service.record(
        db, user=user, action="pack.install", resource_type="connector_pack",
        resource_id=manifest.get("name", ""), request=request,
        detail={
            "pack_version": manifest.get("version"),
            "installed": written,
            "skip_modified": skip_modified,
        },
    )

    return {
        "status": "installed",
        "installed": written,
        "skip_modified": skip_modified,
    }
