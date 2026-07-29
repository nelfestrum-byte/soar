# Plan: system prompt refresh

Spec: `docs/compose/specs/2026-07-29-system-prompt-refresh-design.md`

Docs-only, no code — "test-first" doesn't apply; verification is manual
read-through + the API's existing endpoint (no new test needed, per spec
[S5]'s last bullet: the endpoint already serves the file as-is).

- [x] Re-verify RBAC facts in [S3] directly against current source
      (`orchestrator/api/{actions,connectors,workflows,jobs,logs,tools,
      status,prompts,audit,transfer}.py`, `orchestrator/auth/router.py`) —
      done during spec-writing, table in spec is the checked-in record.
- [ ] Edit `orchestrator/prompts/system_prompt.md`:
  - [ ] Rewrite §6 risk item "P6" → accurate write-only/redaction
        behavior + `"********"` placeholder note + merge-on-write
        reminder (don't send back a real value in place of the
        placeholder unless actually changing it).
  - [ ] Insert new section after §2 ("The three entity contracts"),
        before what is currently §3 ("Dev loop") — title "Your access
        (role `agent`)". Content: one-line boundary statement, bullet
        list of the four excluded endpoint groups, the B3
        `PUT /connectors/{name}/code` exception called out distinctly
        from what `agent` *can* do to connectors (config, create,
        delete, restore code+config).
  - [ ] Renumber all following `##` sections (+1 each).
- [ ] Read the whole file back once, end to end, to confirm numbering is
      sequential and no section now contradicts another (e.g. §2's
      connector description shouldn't re-state the B3 exception in a way
      that conflicts with the new section's wording — one canonical
      statement, cross-reference if needed rather than duplicate).
- [ ] `python -m pytest tests/orchestrator/api/test_prompts_api.py -v` (or
      the closest existing test file for `/prompts/system`) — confirm it
      still passes; it should be unaffected (checks status code /
      response shape, not content), but run it to be sure the fixture
      path used by tests isn't a stale copy of this file.
- [x] Addendum [S3a]: rename §2 to "Entity contracts", add `Tool` as a
      fourth, explicitly read-only bullet, narrow the "read/written
      through symmetric API groups" paragraph to the three CRUD entities.
- [ ] Write report: `docs/compose/reports/system-prompt-refresh.md`.
- [ ] `AGENTS.md`: bump version entry (v0.15) — one-paragraph summary,
      no architecture change, so no other AGENTS.md section needs
      editing.
- [ ] `CHANGELOG.md`: one-line v0.15 entry linking spec/plan/report.
