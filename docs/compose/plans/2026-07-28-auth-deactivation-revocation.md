# Plan: Auth Deactivation Revokes Access (B1)

Spec: `docs/compose/specs/2026-07-28-auth-deactivation-revocation-design.md`

## service.py

- [x] Add failing test `test_rotate_refresh_token_returns_none_for_inactive_user` to `tests/orchestrator/auth/test_service.py` (valid, unrevoked, unexpired refresh token + `is_active=False` user)
- [x] Add failing test `test_rotate_refresh_token_does_not_revoke_token_when_user_inactive` (same setup — token's `revoked_at` stays `None` after the `None`-returning call, so reactivation doesn't lose the session)
- [x] Add failing test `test_update_user_deactivate_revokes_all_refresh_tokens` (`update_user(is_active=False)` marks previously-unrevoked `RefreshToken` rows for that user)
- [x] Add failing test `test_update_user_deactivate_does_not_touch_other_users_tokens`
- [x] Add failing test `test_update_user_role_change_revokes_refresh_tokens` (`update_user(role="viewer")`, `is_active` untouched)
- [x] Add failing test `test_update_user_reactivate_does_not_restore_revoked_tokens`
- [x] Add failing test `test_set_user_active_false_revokes_refresh_tokens` (CLI path, `tests/orchestrator/auth/test_service.py` — exercises the service function directly, not the subprocess CLI)
- [x] Confirm all of the above fail against current `orchestrator/auth/service.py`
- [x] Add `_revoke_all_refresh_tokens(db, user_id)` helper per spec [S2].2
- [x] `rotate_refresh_token()`: move the `User` lookup before `db.commit()`, return `None` if `user is None or not user.is_active`, without marking the token `revoked_at` (per [S4] — default is to not revoke)
- [x] `update_user()`: track `role_changed`, call `_revoke_all_refresh_tokens` when `is_active is False or role_changed`, before `db.commit()`
- [x] `set_user_active()`: call `_revoke_all_refresh_tokens` when `is_active is False`, before `db.commit()`
- [x] Confirm all new tests pass; confirm existing `test_service.py` tests still pass unchanged

Note: `test_rotate_refresh_token_does_not_revoke_token_when_user_inactive` flips
`user.is_active` directly on the ORM object instead of going through
`set_user_active()` — once both fixes are in place, the service-level
deactivation path always mass-revokes, so the only way to reach "live token +
inactive user" (the scenario `rotate_refresh_token()`'s own guard covers) is a
direct row edit, e.g. legacy data from before this fix or an out-of-band write.

## Router integration test

- [x] Add failing test `test_refresh_fails_after_deactivation` to `tests/orchestrator/api/test_auth_api.py`: login -> refresh succeeds -> `PATCH /auth/users/{id} {is_active: false}` -> same refresh token now `401`
- [x] Confirm it fails against current code
- [x] Confirm it passes after the `service.py` fix (no router changes needed per spec)

## Docs (Success Criteria)

- [x] Update known-limitation #7 in `docs/agents/known-limitations.md` to note deactivation now revokes live refresh-token sessions (B1 fixed), narrowing the remaining accepted risk to the last-admin lockout scenario itself
- [x] Update P15 in `docs/concepts/UPGRADE-v2.md` with the same clarification

## Verification

- [x] `python -m pytest tests/orchestrator/auth/ -v` — all green
- [x] `python -m pytest tests/ -q` — only the pre-existing `tests/soar/tools/test_openapi.py::test_generate_config` failure remains, zero new failures
- [x] Write report at `docs/compose/reports/auth-deactivation-revocation.md`
