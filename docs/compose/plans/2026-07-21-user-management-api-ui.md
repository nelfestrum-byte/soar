# Plan: User management via API/UI

Spec: [`docs/compose/specs/2026-07-21-user-management-api-ui-design.md`](../specs/2026-07-21-user-management-api-ui-design.md)

## Phase 1 — Service layer

- [ ] Add failing tests to `tests/orchestrator/auth/test_service.py`:
  - `list_users` returns all created users
  - `get_user_by_id` returns `None` for unknown id
  - `update_user`: role change persists; `is_active` toggle persists;
    password reset — old password no longer authenticates, new one does;
    unknown id raises `LookupError`; calling with all-`None` kwargs is a
    no-op that still returns the current row (no crash)
- [ ] `orchestrator/auth/service.py`: add `list_users`, `get_user_by_id`,
  `update_user` per spec [S2] signatures. Password reset reuses
  `hash_password()` already in this module.
- [ ] Run `python -m pytest tests/orchestrator/auth/test_service.py -v`

## Phase 2 — Schemas

- [ ] `orchestrator/auth/schemas.py`: add `UserCreate`, `UserUpdate` with
  the shared role validator (import `ROLES` from
  `orchestrator.auth.service`) per spec [S2]. Reuse existing `UserOut` for
  responses — do not add a new output schema.
- [ ] Quick sanity check (no dedicated test file needed — covered by the
  router tests in Phase 3): `UserCreate(username="a", password="short", role="admin")`
  raising a validation error is exercised end-to-end via the API test for
  a too-short password.

## Phase 3 — `/auth/users` endpoints + audit

- [ ] Add failing tests to `tests/orchestrator/api/test_auth_api.py`:
  - `POST /auth/users` as admin → 200, `UserOut` in body, no `password`/
    `password_hash` key anywhere in the response JSON
  - `POST /auth/users` as viewer/analyst → 403
  - `GET /auth/users` as admin → includes created users; as viewer → 403
  - `PATCH /auth/users/{id}` as admin: role change persists (verify via a
    follow-up login using the new role's permissions, or via `GET
    /auth/users`); `is_active: false` then login attempt → 401; password
    reset then login with new password → 200
  - `PATCH /auth/users/{id}` targeting **self** with `is_active: false` →
    409, account still active afterward
  - `PATCH /auth/users/{id}` for unknown id → 404
  - Audit: create + update each write one `AuditLog` row
    (`resource_type="user"`), `detail` for a password-reset update
    contains `password_reset: true` and **not** the raw password string
- [ ] `orchestrator/auth/router.py`: add the three routes per spec [S2] —
  `require_role("admin")`, `audit_service.record(...)` on create/update,
  409 self-lockout check on `PATCH` before calling `update_user`
- [ ] Run `python -m pytest tests/orchestrator/api/test_auth_api.py -v`
- [ ] Run the full auth-adjacent suite:
  `python -m pytest tests/orchestrator/auth/ tests/orchestrator/api/test_auth_api.py -v`

## Phase 4 — UI

- [ ] `ui/src/api.js`: add `listUsers()`, `createUser(username, password, role)`,
  `updateUser(id, patch)` (`patch` = `{role?, is_active?, password?}`),
  following the existing `listApiKeys`/`createApiKey` shape
- [ ] `ui/src/views/Users.vue` (new) per spec [S3] — copy `ApiKeys.vue`
  structure: table, new-user form, per-row role `<select>` (auto-save on
  `change`), Activate/Deactivate button, inline "Reset password" input.
  Mark/disable the Deactivate action on the row matching `auth.username`
  (client-side UX only, real guard is server-side)
- [ ] `ui/src/main.js`: add `{ path: '/users', component: () =>
  import('./views/Users.vue') }`
- [ ] `ui/src/App.vue`: add nav link `v-if="auth.role === 'admin'"` next to
  the existing `/api-keys` link
- [ ] Manual verification: `cd ui && npm run dev`, log in as the stage
  admin, exercise create/list/role-change/deactivate/reactivate/password-reset
  through the browser, confirm self-deactivate is blocked in the UI

## Phase 5 — Docs

- [ ] `README.md` auth section: replace the CLI-only framing for user
  management — CLI stays documented as the bootstrap path, add the
  `/auth/users` `curl` examples (mirror the existing `/auth/keys` block)
- [ ] `AGENTS.md`: update the Auth endpoints table (`### Auth`) with the
  three new routes; update File map row for user management; note in the
  Authentication section that `/auth/users` mirrors `/auth/keys` (admin,
  audited)
- [ ] Write `docs/compose/reports/user-management-api-ui.md` per repo
  convention

## Test commands (full pass before considering done)

```bash
python -m pytest tests/ -v
ruff check .
```
