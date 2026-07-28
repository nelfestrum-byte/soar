# Report: Auth Deactivation Revokes Access (B1)

Spec: `docs/compose/specs/2026-07-28-auth-deactivation-revocation-design.md`
Plan: `docs/compose/plans/2026-07-28-auth-deactivation-revocation.md`

## Summary

`PATCH /auth/users/{id} {is_active: false}` and `deactivate-user` (CLI)
blocked new `/auth/login` attempts but left any already-issued refresh token
alive — `POST /auth/refresh` would rotate it into a fresh access+refresh pair
forever, so a deactivated (potentially compromised) account never actually
lost access short of `refresh_token_ttl` (default 7 days) idle expiry.
Implemented both fixes from the spec's [S2], in `orchestrator/auth/service.py`:

1. `rotate_refresh_token()` now looks up the `User` before deciding to rotate
   (moved ahead of the mutation, not just before returning it in the pair)
   and returns `None` if the user is missing or `is_active` is `False`. Per
   spec [S4], this does **not** mark the token `revoked_at` — a live token
   for a since-reactivated user still works, mirroring how an expired token
   is also left un-revoked today.
2. New `_revoke_all_refresh_tokens(db, user_id)` helper (single `UPDATE ...
   WHERE user_id = ? AND revoked_at IS NULL`) called from `update_user()`
   when `is_active` is set to `False` **or** `role` changes, and from
   `set_user_active()` when deactivating — both in the same transaction as
   the user row update, so both the API path and the CLI path get the fix
   without duplicated logic. Reactivation (`is_active: true`) does not call
   it and does not un-revoke anything.

`router.py` was not touched — `rotate_refresh_token() is None` already maps
to the same `401 Invalid or expired refresh token` used for
expired/already-revoked tokens, so a deactivated account gets no
distinguishable error.

Out of scope (per spec [S2]/[S3], unchanged): revoking already-issued
**access** tokens (stateless JWT, no denylist) — worst case exposure window
is `access_token_ttl` (default 1800s), not indefinite as before. `ApiKey`
deactivation was already immediate (checked on every request in
`get_api_key()`), not touched.

## Files changed

- `orchestrator/auth/service.py` — `_revoke_all_refresh_tokens()`;
  `rotate_refresh_token()` now checks `User.is_active` before rotating;
  `update_user()` revokes on `is_active=False` or role change;
  `set_user_active()` revokes on deactivation.
- `tests/orchestrator/auth/test_service.py` — 7 new tests covering
  `rotate_refresh_token`/`update_user`/`set_user_active` per spec [S4].
- `tests/orchestrator/api/test_auth_api.py` — `test_refresh_fails_after_deactivation`,
  full login -> refresh -> deactivate -> refresh(401) sequence via the API.
- `docs/agents/known-limitations.md` — #7 updated to note deactivation/role
  change now revokes live refresh-token sessions immediately (B1).
- `docs/concepts/UPGRADE-v2.md` — P15 narrative updated with the same
  clarification; the last-admin-lockout accepted-risk decision itself is
  unchanged.
- `docs/compose/plans/2026-07-28-auth-deactivation-revocation.md`,
  `docs/compose/reports/auth-deactivation-revocation.md` (this report).

## Testing

All new tests were written first and confirmed to fail against the
pre-change `service.py`/router (7 in `test_service.py` +
`test_refresh_fails_after_deactivation`), then made to pass by the
implementation.

`tests/orchestrator/auth/ tests/orchestrator/api/test_auth_api.py`:

```
74 passed, 4 warnings in 41.15s
```

Full suite `python -m pytest tests/ -q`:

```
1 failed, 694 passed, 1 skipped, 13 warnings in 113.86s
```

The one failure, `tests/soar/tools/test_openapi.py::test_generate_config`, is
the known pre-existing failure unrelated to this work (fixed by a separate
spec) — confirmed present before this change and unchanged in nature/count
after it. Zero new failures introduced.

One test (`test_rotate_refresh_token_does_not_revoke_token_when_user_inactive`)
flips `user.is_active` directly on the ORM object rather than through
`set_user_active()`: once both fixes are in place, the service-level
deactivation path always mass-revokes tokens, so the only way to reproduce
"live refresh token + inactive user" — the exact case `rotate_refresh_token()`'s
own guard covers — is a direct row edit (e.g. data predating this fix, or an
out-of-band write). This is noted inline in the test and in the plan.

## Success criteria (spec S5)

- [x] Deactivated user gets `401` on `/auth/refresh`, regardless of whether
      the specific refresh token was created before or after deactivation
- [x] `PATCH /auth/users/{id} {is_active: false}` and `deactivate-user` CLI
      revoke all live refresh tokens in the same transaction
- [x] Role change via the same path also revokes live refresh tokens
- [x] Reactivation (`is_active: true`) does not restore old tokens — user
      must go through `/auth/login` again
- [x] `ApiKey`/service path unaffected (already correct, untouched)
- [x] P15 in `UPGRADE-v2.md` and known-limitation #7 in
      `known-limitations.md` updated to reflect working deactivation
