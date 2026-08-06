#!/usr/bin/env pwsh
# Thin wrapper so `./soarctl.ps1 ...` works from the repo root on Windows —
# PowerShell counterpart of the bash `soarctl` wrapper (which needs a POSIX
# shell), for build machines without one — see
# docs/compose/specs/2026-08-06-package-version-default-design.md.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$scriptDir/deploy/soarctl" @args
exit $LASTEXITCODE
