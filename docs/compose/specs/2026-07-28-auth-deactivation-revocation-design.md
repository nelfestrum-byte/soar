# Auth Deactivation Revokes Access (B1)

> Реализует B1 из `docs/concepts/BAGFIX_PLAN.md` (источник:
> `docs/compose/reports/prod-readiness-review-2026-07-27.md`). Блокер
> пилота — до фикса деактивация пользователя не отзывает уже выданный
> доступ.

## [S1] Problem

`authenticate_user()` (`orchestrator/auth/service.py:43-48`) фильтрует по
`User.is_active == True` — но это влияет только на `/auth/login`.
`rotate_refresh_token()` (`orchestrator/auth/service.py:63-93`), вызываемый
из `POST /auth/refresh` (`orchestrator/auth/router.py:57-72`), проверяет
только `RefreshToken.revoked_at` и `RefreshToken.expires_at` — не читает
`User` дальше, чем нужно для копирования `user_id` в новый токен. Итог:

- `PATCH /auth/users/{id} {is_active: false}` → `update_user()`
  (`service.py:173-188`) меняет только флаг на `User`, не трогает
  `RefreshToken`.
- `python -m orchestrator.auth.cli deactivate-user` → `set_user_active()`
  (`service.py:152-160`) — то же самое, тот же дефект.
- Деактивированный пользователь не может получить новый access-токен через
  `/auth/login` (заблокировано), но уже выданный refresh-токен продолжает
  работать через `/auth/refresh` **бессрочно**: каждый вызов ротирует его
  на новый refresh (`refresh_token_ttl`, дефолт 7 дней) и выдаёт свежий
  access-токен (`access_token_ttl`, дефолт 30 минут). Ничто не останавливает
  цепочку.

Это единственный API-путь отозвать доступ скомпрометированному
пользователю/агенту в системе без сессий на сервере (JWT stateless по
access-токену). Ломает и recovery-путь принятого риска P15
(`docs/concepts/UPGRADE-v2.md`, known-limitation #7 в
`docs/agents/known-limitations.md`) — тот описывает `deactivate-user` как
работающий механизм сдерживания, но он не отзывает уже живые сессии.

## [S2] Solution

Два независимых изменения, оба обязательны:

1. **`rotate_refresh_token()` — проверять `User.is_active`.** Сейчас
   функция вообще не читает пользователя до момента, когда уже нужно
   вернуть его в паре `(user, new_raw)`. Достаточно объединить проверку с
   уже существующим запросом пользователя (`service.py:89-90`) — переместить
   его перед решением ротировать, и до `db.commit()`:

   ```python
   async def rotate_refresh_token(
       db: AsyncSession, raw_token: str, ttl: int
   ) -> tuple[User, str] | None:
       h = _token_hash(raw_token)
       result = await db.execute(
           select(RefreshToken)
           .where(RefreshToken.token_hash == h, RefreshToken.revoked_at == None)  # noqa: E711
           .with_for_update()
       )
       token = result.scalar_one_or_none()
       if not token:
           return None
       if token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
           return None

       user_result = await db.execute(select(User).where(User.id == token.user_id))
       user = user_result.scalar_one_or_none()
       if user is None or not user.is_active:
           return None

       token.revoked_at = datetime.now(UTC)
       new_raw = secrets.token_urlsafe(48)
       new_token = RefreshToken(
           user_id=token.user_id,
           token_hash=_token_hash(new_raw),
           expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
       )
       db.add(new_token)
       await db.commit()
       return user, new_raw
   ```

   Симметрично с `authenticate_user()`, которая уже требует `is_active`
   на login. `router.py` не меняется — `rotate_refresh_token() is None` уже
   маппится на `401 Invalid or expired refresh token`, тот же ответ, что и
   для просроченного/отозванного токена (не различаем причину в теле
   ответа — не даём атакеру понять, деактивирован ли аккаунт).

2. **Отзыв всех живых refresh-токенов при деактивации/смене роли —
   на уровне `service.py`, не роутера**, чтобы оба вызывающих пути
   (`update_user()` из API и `set_user_active()` из CLI) получили фикс
   без дублирования логики:

   ```python
   async def _revoke_all_refresh_tokens(db: AsyncSession, user_id: int) -> None:
       await db.execute(
           update(RefreshToken)
           .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at == None)  # noqa: E711
           .values(revoked_at=datetime.now(UTC))
       )
   ```

   Вызывается из `update_user()` при `is_active=False` **и** при смене
   `role` (смена роли — тоже эскалация/деэскалация прав, старый
   access-токен несёт старую роль до истечения TTL, но новый refresh-цикл
   не должен пролонгировать доступ со старой ролью бесконечно; access-токен
   с истёкшей ролью живёт максимум `access_token_ttl`, это принятое окно,
   как и сегодня) — до `db.commit()` в той же транзакции:

   ```python
   async def update_user(
       db: AsyncSession, user_id: int, *,
       role: str | None = None, is_active: bool | None = None, password: str | None = None,
   ) -> User:
       user = await get_user_by_id(db, user_id)
       if not user:
           raise LookupError(f"No such user id: {user_id}")
       role_changed = role is not None and role != user.role
       if role is not None:
           user.role = role
       if is_active is not None:
           user.is_active = is_active
       if password is not None:
           user.password_hash = hash_password(password)
       if is_active is False or role_changed:
           await _revoke_all_refresh_tokens(db, user_id)
       await db.commit()
       await db.refresh(user)
       return user
   ```

   `set_user_active()` (CLI path) gets the same call when `is_active=False`:

   ```python
   async def set_user_active(db: AsyncSession, username: str, is_active: bool) -> User:
       result = await db.execute(select(User).where(User.username == username))
       user = result.scalar_one_or_none()
       if not user:
           raise LookupError(f"No such user: {username}")
       user.is_active = is_active
       if is_active is False:
           await _revoke_all_refresh_tokens(db, user.id)
       await db.commit()
       await db.refresh(user)
       return user
   ```

Не в скоупе: отзыв активных **access**-токенов (JWT, stateless, не
проверяются по БД — нет механизма отозвать конкретный access-токен без
введения denylist, что отдельная архитектурная фича, не точечный фикс).
Access-токен деактивированного пользователя продолжает быть технически
валидным до истечения `access_token_ttl` (дефолт 1800s/30 минут) — это уже
принятое и задокументированное поведение JWT, не регрессия этого фикса;
после экспирации ре-аутентификация невозможна (`/auth/login` — 401) и
рефреш невозможен (после [S2].1). Худший случай простоя отзыва — окно
`access_token_ttl`, не бессрочно, как сейчас.

## [S3] API keys — не затронуты

`ApiKey.is_active` уже проверяется в `get_api_key()`
(`service.py:109-121`) на каждый запрос без кэширования — деактивация
service-аккаунта (`agent`/`service` роль через API key) уже отзывает
доступ немедленно, в этот трек не входит.

## [S4] Testing Strategy

Новые/изменённые в `tests/orchestrator/auth/test_service.py` (unit,
`rotate_refresh_token`/`update_user`/`set_user_active`) и
`tests/orchestrator/auth/test_cli.py` (CLI path):

- `rotate_refresh_token()` возвращает `None`, если `User.is_active is
  False` (валидный, неотозванный, непросроченный refresh-токен + неактивный
  пользователь).
- `rotate_refresh_token()` не помечает токен `revoked_at`, если возвращает
  `None` по причине `is_active` (не тратим живой токен впустую при гонке —
  повторная попытка после реактивации должна снова сработать тем же
  токеном; альтернативно можно и стоит отозвать — решить при реализации,
  какая семантика безопаснее: сохранить токен → пользователь, реактивированный
  посреди инцидента, не теряет сессию; отозвать сразу → более консервативно.
  Дефолт для реализации — **не отзывать**, симметрично тому, что просроченный
  токен тоже не удаляется явно).
- `update_user(db, user_id, is_active=False)` помечает `revoked_at`
  всем ранее неотозванным `RefreshToken` этого пользователя; уже
  отозванные/чужие — не трогает.
- `update_user(db, user_id, role="viewer")` (смена роли без смены
  `is_active`) тоже отзывает все живые refresh-токены пользователя.
- `update_user(db, user_id, is_active=True)` (реактивация) не отзывает
  ничего нового и не восстанавливает уже отозванные токены.
- `set_user_active(db, username, False)` (CLI-путь) — тот же эффект, что
  и `update_user`.
- Интеграционный тест на роутере (`tests/orchestrator/api/test_auth_*.py`
  либо новый файл): деактивированный пользователь получает `401` на
  `POST /auth/refresh` со своим последним валидным refresh-токеном, даже
  если токен не был явно отозван до вызова `PATCH /auth/users/{id}`
  (последовательность: login → refresh работает → деактивация →
  тот же/новый refresh-токен → 401).

## [S5] Success Criteria

- [ ] Деактивированный пользователь получает `401` на `/auth/refresh`,
      независимо от того, был ли конкретный refresh-токен создан до или
      после деактивации (в пределах текущей активной цепочки)
- [ ] `PATCH /auth/users/{id} {is_active: false}` и
      `deactivate-user` CLI мгновенно (в той же транзакции) отзывают все
      живые refresh-токены пользователя
- [ ] Смена роли тем же путём тоже отзывает живые refresh-токены
- [ ] Реактивация (`is_active: true`) не восстанавливает старые токены —
      пользователь обязан пройти `/auth/login` заново
- [ ] `ApiKey`/`service`-путь не регрессирует (уже корректен, не трогается)
- [ ] P15 в `UPGRADE-v2.md` и known-limitation #7 в
      `docs/agents/known-limitations.md` отражают рабочую деактивацию
      (см. D6 — правится вместе с этим фиксом, не раньше)
