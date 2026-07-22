# User management via API/UI

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/user-management-api-ui.md)
>
> Plan: `docs/compose/plans/2026-07-21-user-management-api-ui.md`

## [S1] Problem

User lifecycle (`create-user` / `deactivate-user` / `activate-user`, added
in [`2026-07-21-auth-cli-user-lifecycle-design.md`](2026-07-21-auth-cli-user-lifecycle-design.md))
is CLI-only today — an admin has to `docker compose exec` into the
orchestrator container for every single change. API keys already have full
CRUD over `/auth/keys` plus an admin-only UI page
(`ui/src/views/ApiKeys.vue`). Users don't: no `/auth/users` routes, no
`Users.vue`. Now that auth is actually enabled on stage (previous session),
this gap is a real day-2-ops problem — onboarding/offboarding an analyst
currently requires shell access to the orchestrator container.

## [S2] Solution

Mirror the API-keys shape exactly — same RBAC (`admin`-only), same audit
logging via `orchestrator.audit.service.record`, same UI card/table
pattern — for users.

### Endpoints (`orchestrator/auth/router.py`, admin-only)

```
POST   /auth/users        create — {username, password, role}
GET    /auth/users        list — [UserOut] (no password_hash, ever)
PATCH  /auth/users/{id}   partial update — {role?, is_active?, password?}
```

No hard `DELETE` — soft-delete via `is_active` is the standing decision
from the CLI-lifecycle spec, unchanged here. One `PATCH` covers
activate/deactivate, role change, and password reset (admin resetting a
forgotten password) instead of three separate routes — keeps the surface
proportional to what's actually needed, matches how `ApiKeyCreate` already
folds multiple optional fields into one payload.

**Self-lockout guard:** `PATCH /auth/users/{id}` rejects (409) an attempt
by the acting admin to deactivate their **own** account
(`current_user.id == id and body.is_active is False`). Cheap to add,
prevents a real support headache (admin locks themselves out, nobody left
who can flip `is_active` back without CLI/DB access). Does **not** guard
against demoting the last remaining admin's role or deactivating a
*different* admin — out of scope, same reasoning as "no `list-users`
guard" in the CLI spec: solve the common accidental-self-lockout case, not
every hypothetical.

### Service layer (`orchestrator/auth/service.py`)

New, id-based (the API/UI work with `id`, unlike the CLI which takes
`--username`):

```python
async def list_users(db: AsyncSession) -> list[User]: ...
async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None: ...
async def update_user(
    db: AsyncSession, user_id: int, *,
    role: str | None = None, is_active: bool | None = None, password: str | None = None,
) -> User:
    """Raises LookupError if user_id doesn't exist."""
```

Existing `set_user_active(db, username, is_active)` (CLI) is untouched —
different call shape (username vs. id), no reason to collapse them into
one function just to share code neither caller needs the other's shape
for.

### Schemas (`orchestrator/auth/schemas.py`)

```python
class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8)
    role: str = Field(default="analyst")

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v):
        if v not in ROLES:  # from orchestrator.auth.service
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        return v


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    # same role validator as UserCreate, skipped when None
```

`UserOut` already exists (`id, username, role, is_active, created_at,
last_login_at`) — reused as-is for both list and the create/update
response. Password is **never** included in any response schema.

### Audit trail

`user.create` on `POST`, `user.update` on `PATCH` — same
`audit_service.record(db, user=..., action=..., resource_type="user",
resource_id=str(user.id), request=request, detail={...})` call already
used for `apikey.create`/`apikey.delete`. `detail` for `user.update` lists
which fields changed (`{"role": "admin"}` etc.) but **never** includes the
password value itself, only a boolean `password_reset: true` flag when
present — passwords must never land in `audit_log.detail` (JSON column,
readable via `GET /audit-log`).

## [S3] UI

New `ui/src/views/Users.vue`, structural copy of `ApiKeys.vue`: table
(username / role / status badge / created_at / last_login_at / actions),
"New User" form (username, password, role dropdown), inline role
`<select>` per row with auto-save on change, Activate/Deactivate button
per row, "Reset password" button opening a small inline password input.
Own row is visually marked and its Deactivate button disabled client-side
(the real guard is server-side per [S2], this is just UX — avoid a
pointless round-trip to a 409 for the common case).

- `main.js`: new route `/users`
- `App.vue`: new nav link, `v-if="auth.role === 'admin'"` (same guard as
  the existing `/api-keys` link)
- `api.js`: `listUsers()`, `createUser(username, password, role)`,
  `updateUser(id, {role?, is_active?, password?})`

## [S4] Non-goals

- No hard delete (unchanged from the CLI-lifecycle spec's decision).
- No self-service password change / profile page — this is *admin*
  managing *other* users, not a user managing themselves. `/auth/me` stays
  read-only.
- No protection against deactivating/demoting the last admin account
  (other than self-lockout) — flagged as a known gap, not blocking.
- CLI (`create-user`/`deactivate-user`/`activate-user`) is **not**
  removed — stays the bootstrap path before any admin account exists via
  the API (chicken-and-egg: you need an authenticated admin to call
  `POST /auth/users`).

## [S5] Testing strategy

- `tests/orchestrator/auth/test_service.py`: extend with `list_users`,
  `get_user_by_id`, `update_user` (role change, is_active toggle, password
  reset — verify new password actually authenticates and old one doesn't,
  unknown id → `LookupError`).
- `tests/orchestrator/api/test_auth_api.py`: extend with endpoint-level
  cases mirroring the existing API-key tests — admin create/list/update,
  viewer/analyst forbidden (403), self-deactivation rejected (409), audit
  rows written for create/update, password field absent from all
  responses.

## [S6] Success criteria

- [ ] Admin can create, list, and update (role/active/password) users
      entirely through the UI, no CLI/shell access needed
- [ ] Non-admin roles get 403 on all `/auth/users` routes
- [ ] Admin cannot deactivate their own account via the API/UI
- [ ] Audit log records `user.create`/`user.update`, never the password
- [ ] CLI still works unmodified (bootstrap path)
- [ ] Full test suite + `ruff check .` pass
