---
feature: user-management-api-ui
status: delivered
specs:
  - docs/compose/specs/2026-07-21-user-management-api-ui-design.md
plans:
  - docs/compose/plans/2026-07-21-user-management-api-ui.md
branch: main
commits: pending
---

# User management via API/UI — Final Report

## What Was Built

Full admin-facing user lifecycle management through the API and UI,
mirroring the existing API-keys pattern (`/auth/keys` + `ApiKeys.vue`).
Previously the only way to create/deactivate a user was CLI + shell access
to the orchestrator container; now an admin manages users end-to-end from
the browser.

## What Changed

### Backend

- `orchestrator/auth/service.py`: `list_users`, `get_user_by_id`,
  `update_user(db, user_id, *, role=None, is_active=None, password=None)`
  (id-based — distinct from the CLI's username-based `set_user_active`,
  different callers, no shared-shape benefit to merging them).
- `orchestrator/auth/schemas.py`: `UserCreate`, `UserUpdate` (role
  validated against `service.ROLES`); `UserOut` reused for all responses
  — password/password_hash never serialized.
- `orchestrator/auth/router.py`: `POST /auth/users`, `GET /auth/users`,
  `PATCH /auth/users/{id}` — all `admin`-only. One `PATCH` handles role
  change, activate/deactivate, and password reset instead of three
  routes. `PATCH` on your own account with `is_active: false` → `409`
  (self-lockout guard — an admin can deactivate *other* admins, not
  themselves). Duplicate username on create → `409`. Every create/update
  writes an `audit_log` row (`user.create`/`user.update`) via the existing
  `audit_service.record`; the `detail` JSON never contains a raw password,
  only a `password_reset: true` flag when one was set.

### UI

- `ui/src/views/Users.vue` (new): table (username, inline role `<select>`
  with auto-save, status badge, last login, actions), "New User" form,
  Activate/Deactivate button (disabled client-side on your own row —
  real guard is server-side), inline "Reset password" input.
- `ui/src/api.js`: `listUsers`, `createUser`, `updateUser`.
- `ui/src/main.js` / `App.vue`: `/users` route, nav link gated on
  `auth.role === 'admin'` (same pattern as the existing `/api-keys` link).

### CLI (unchanged, still needed)

`create-user`/`deactivate-user`/`activate-user` remain — they're the only
way to bootstrap the first admin account before any user exists to call
the now-protected `/auth/users` API.

## Verification

- New/extended tests: `tests/orchestrator/auth/test_service.py` (+7 cases
  — list/get/update, role change, deactivate-blocks-auth, password reset
  old/new, unknown id), `tests/orchestrator/api/test_auth_api.py` (+12
  cases — create/list/update RBAC, role change, deactivate blocks login,
  password reset blocks old password, self-deactivate 409, unknown-user
  404, audit rows for create+update with no password leakage).
- `python -m pytest tests/orchestrator -q` (excluding connector tests with
  missing optional deps, pre-existing and unrelated): **282 passed, 1
  skipped**.
- `ruff check orchestrator/auth/ tests/orchestrator/auth/
  tests/orchestrator/api/test_auth_api.py`: clean.
- `cd ui && npm run build`: clean, `Users.vue` bundled
  (`Users-*.js`, 4.42 kB gzip 1.64 kB).
- **Live verification on the redeployed stage instance** (rebuilt +
  restarted `orchestrator`/`ui` containers, Postgres/Redis untouched):
  - `POST /auth/users` → 200, user created; visible in `GET /auth/users`
  - `PATCH .../{own_id}` with `is_active: false` → **409**, login as that
    admin still works afterward
  - `PATCH .../{other_id}` with `is_active: false` → 200; that user's
    subsequent `/auth/login` → **401**
  - `GET /audit-log?resource_type=user` → both `user.create` and
    `user.update` rows present, correct `detail`, no password anywhere in
    the response
  - UI reachable at `:3000`, `/users` SPA route resolves via nginx
    fallback (200)
- **Not performed**: interactive browser click-through of `Users.vue` (no
  browser automation tool available in this session) — verified instead
  via a clean production `vite build` (catches template/script errors)
  plus full API-level exercise of every action the page performs
  (create/list/role-change/deactivate/reactivate/password-reset/
  self-lockout). Recommend a manual pass in an actual browser before
  treating this as fully signed off.
