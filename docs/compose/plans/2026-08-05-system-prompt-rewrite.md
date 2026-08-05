# Plan: system prompt rewrite

Spec: `docs/compose/specs/2026-08-05-system-prompt-rewrite-design.md`

Docs-only, no code — "test-first" doesn't apply; verification is manual
read-through + the existing content-agnostic test.

- [x] Re-verify facts in [S3] directly against current source
      (`orchestrator/config.py`, `orchestrator/api/workflows.py`,
      `orchestrator/api/runtime.py`, `orchestrator/api/tools.py`,
      `soar/tools/__init__.py`, `docs/concepts/ENTITY-MODEL.md`,
      `docs/compose/reports/tools-redesign.md`) — done during spec-writing.
- [ ] Edit `orchestrator/prompts/system_prompt.md`:
  - [ ] §3 (was §2, "Entity contracts") — replace hardcoded `soar/...`
        paths with references to the configured directories
        (`connectors_dir`/`actions_dir`/`workflows_dir`); keep the rest of
        the section's content (registry-key-by-filename, `BaseConnector`/
        `_ensure_connected`, Tool read-only) as-is.
  - [ ] Insert new §4 "Using a connector from your code" right after
        entity contracts, before the RBAC section — both import forms,
        concept form preferred (credential scoping + import-time failure),
        one short example.
  - [ ] Renumber old §3→§5 (RBAC), §4→§6 (dev loop), §5→§7
        (self-description), §6→§8 (conventions), §7→§9 (risks).
  - [ ] §6 (dev loop, was §4) — add clause to validate-before-write bullet:
        syntax/entry-point only, not import resolution; cross-reference
        new §9 item.
  - [ ] §7 (self-description, was §5) — rewrite `/tools` bullet to name
        `LoggingHttpClient`/`CachingHttpClient`/`new_client`/
        `WatermarkStore`/`SeenStore` (current `TOOL_REGISTRY`); add
        `GET /runtime` bullet (guaranteed vs present-not-guaranteed).
  - [ ] §8 (conventions, was §6) — add bullet: static/module-level
        connector imports are what credential scoping sees; cross-ref §4.
  - [ ] §9 (risks, was §7) — add bullet: `PUT .../code` doesn't validate
        import resolution; unresolved imports/instances surface as a job
        traceback (§6), not at write time.
- [ ] Read the whole file back once, end to end — confirm 1-9 numbering
      sequential, no section restates another's content without a
      cross-reference (e.g. don't duplicate the credential-scoping
      rationale in both §4 and §8 — state once, cross-reference).
- [ ] `python -m pytest tests/orchestrator/api/test_prompts_api.py -q` —
      confirm still passes (content-agnostic, expected unaffected).
- [ ] Write report: `docs/compose/reports/system-prompt-rewrite.md`.
- [ ] `AGENTS.md`: bump version entry — one-paragraph summary, no
      architecture change.
- [ ] `CHANGELOG.md`: one-line entry linking spec/plan/report.
