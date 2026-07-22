# Agent Dev-Loop — Этап 3: права доступа под агента

> [!NOTE]
> Реализация Этапа 3 из `UPGRADE.md`. Закрывает P7.
> Plan: `docs/compose/plans/2026-07-22-agent-devloop-stage3.md` (после этого спека).
> Зависит от Этапа 2: новые ручки `describe`/`prompts` (стр. `_RO`) должны
> уже существовать, чтобы это изменение подхватило их автоматически через
> общие константы `_RO` в тех же файлах (см. [S3]).

## [S1] Problem

`PUT`/`DELETE`/`.../restore` кода workflow/action/connector требуют роли
`admin` — единственной роли с доступом и к коду, и к управлению
пользователями (`orchestrator/auth/router.py:136,152,160`), API-ключами
(`router.py:96,108,117`), audit-log (`orchestrator/api/audit.py:30`) и
`/transfer/*` (`orchestrator/api/transfer.py:15`). Чтобы дать агенту
возможность писать код и запускать jobs, сегодня пришлось бы выдать ему
полный административный доступ — включая создание/удаление пользователей
и просмотр аудита действий других акторов.

Роль в БД — обычная строка (`orchestrator/auth/models.py`: `User.role:
Mapped[str] = mapped_column(String(32), ...)`, `ApiKey.role` аналогично),
без `Enum`/`CHECK` на уровне схемы (подтверждено в
`alembic/versions/ea0bb43fc071_initial_auth_and_jobs_tables.py:35,47`) —
новая роль не требует миграции. Но строка проверяется в трёх местах,
которые её отклонят, если не обновить:

1. `orchestrator/auth/service.py:12` — `ROLES = {"admin", "analyst",
   "viewer", "service"}`, используется валидаторами `UserCreate`/
   `UserUpdate` (`orchestrator/auth/schemas.py:39-44,52-57`) для
   `POST /auth/users`/`PATCH /auth/users/{id}`.
2. `orchestrator/auth/cli.py:70` — `argparse` `choices=["admin",
   "analyst", "viewer", "service"]` на `create-user --role`.
3. `deploy/soarctl_lib/users.py:13,17-20` — `_ROLES` + explicit
   `ValueError` check в `create()`, покрыт
   `tests/deploy/test_soarctl_users.py::test_create_rejects_unknown_role`.

(`ApiKeyCreate.role`, `orchestrator/auth/schemas.py:60-63`, валидатора не
имеет — `POST /auth/keys` уже принимает произвольную строку; не требует
изменений для выпуска агентского ключа с новой ролью.)

Плоские tuple-константы `_RO`/`_RW`/`_ADMIN`/`_ANALYST` в каждом
`orchestrator/api/*.py`-роутере — единственный механизм авторизации
(`require_role(*roles)`, `orchestrator/auth/dependencies.py:65-71` — просто
`user.role not in roles`), нет ролевой иерархии/наследования: новая роль
должна быть явно добавлена в каждый tuple, который на неё должен
распространяться.

## [S2] Solution overview

Ввести роль `agent` как обычную строку в трёх точках валидации ([S3]) и в
tuple-константах, которые относятся к "код + запуск jobs" ([S4]). Ручки
`/auth/*`, `/audit-log`, `/transfer/*` используют литерал `"admin"`
напрямую (не общий tuple) — агент исключается из них автоматически, без
единой правки в этих трёх файлах (см. подтверждение ниже — это не
допущение, а свойство текущего кода).

## [S3] Разрешить роль `agent` в валидации

`orchestrator/auth/service.py:12`:

```python
ROLES = {"admin", "analyst", "viewer", "service", "agent"}
```

`orchestrator/auth/cli.py:70`:

```python
create.add_argument("--role", default="analyst", choices=["admin", "analyst", "viewer", "service", "agent"])
```

`deploy/soarctl_lib/users.py:13`:

```python
_ROLES = ("admin", "analyst", "viewer", "service", "agent")
```

Три места, три идентичных списка — сознательно не выносится в общий
источник правды в этом этапе (список ролей уже определён в трёх слоях —
БД-приложение, orchestrator CLI, отдельный деплой-CLI без общего импорта
между собой; унификация — выходит за рамки точечной правки P7).

## [S4] Расширить tuple-константы кода и jobs

Правило: роль `agent` добавляется туда, где сегодня разрешён write кода/
конфига сущностей (workflow/action/connector) или управление jobs
(создание/отмена/логи) — то есть "разработка и запуск", как сформулировано
в `UPGRADE.md` Этап 3. Не добавляется туда, где `require_role("admin")`
задан литералом напрямую (`/auth/*`, `/audit-log`, `/transfer/*`) — эти
пути не имеют общей константы, трогать нечего.

| Файл | Константа | Было | Стало | Что охраняет |
|---|---|---|---|---|
| `actions.py:20` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | list/get/describe/history/diff |
| `actions.py:21` | `_ADMIN` | `(admin,)` | `+ agent` | PUT, DELETE, restore |
| `connectors.py:28` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | list/get/describe/history/diff/config |
| `connectors.py:29` | `_RW` | `(analyst, admin)` | `+ agent` | preview spec (POST/GET) |
| `connectors.py:30` | `_ADMIN` | `(admin,)` | `+ agent` | generate, create, PUT/DELETE code+config, restore |
| `workflows.py:18` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | list/get/history/diff |
| `workflows.py:19` | `_RW` | `(analyst, admin)` | `+ agent` | enable/disable, reload |
| `workflows.py:20` | `_ADMIN` | `(admin,)` | `+ agent` | PUT/DELETE code, restore |
| `jobs.py:13` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | list/get job |
| `jobs.py:14` | `_RW` | `(analyst, service, admin)` | `+ agent` | create job |
| `jobs.py:15` | `_ANALYST` | `(analyst, admin)` | `+ agent` | cancel job |
| `logs.py:13` | `_RW` | `(analyst, service, admin)` | `+ agent` | job log / log stream |
| `tools.py:9` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | list/get tool |
| `status.py:7` | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | `/status` |
| `prompts.py` (Этап 2) | `_RO` | `(viewer, analyst, service, admin)` | `+ agent` | `GET /prompts/system`, `GET /prompts/user` |

**Явно не трогаем** (литерал `"admin"`, без общей константы — агент
остаётся исключён без единой правки):

- `orchestrator/api/audit.py:30` — `GET /audit-log`
- `orchestrator/api/transfer.py:15` — весь `/transfer/*`
- `orchestrator/auth/router.py:96,108,117,136,152,160` — `/auth/keys`,
  `/auth/users`
- `orchestrator/api/prompts.py` `_ADMIN` (Этап 2, `PUT /prompts/user`) —
  не входит в "код+jobs", остаётся `(admin,)`. Пересмотреть, если
  практика Этапа 2 покажет, что агенту нужно редактировать собственный
  пользовательский промпт.

**Почему `_RW`/`_ANALYST` тоже, а не только `_ADMIN`:** формулировка
`UPGRADE.md` — "право на код и jobs" включает возможность включить только
что созданный webhook/scheduled workflow (`enable`), остановить
зациклившийся job, который агент сам запустил (`cancel`), и просмотреть
его лог сверх traceback из `GET /jobs/{id}` (Этап 1 отдаёт только
traceback, не полный stdout). Без этого агент мог бы писать код, но не
управлять его выполнением — цикл остался бы разомкнутым на этапе runtime,
что противоречит цели "разработка и запуск".

**Что агент осознанно НЕ получает на этом этапе:**
маскирование секретов (P6, риск) и ограничение по конкретным ресурсам
внутри роли ("агенту нельзя трогать connector X" — при одной плоской роли
не нужно) — оба явно исключены `UPGRADE.md` из Этапа 3.

## [S5] Проверка отсутствия побочного расширения admin-контура

Ручной аудит перед реализацией (фиксируется как чек-лист в плане, не
код): `grep -rn 'require_role(' orchestrator/` должен показать, что
единственные места со строкой `"admin"` напрямую (не через `_ADMIN`
tuple) — это шесть точек `/auth/*`/`/audit-log`/`/transfer/*`,
перечисленные в [S4]. Если найдётся седьмое — это регрессия/новый код,
попавший в РБАК без учёта Этапа 3, разбирать отдельно перед мерджем.

## [S6] Testing strategy

- `tests/orchestrator/auth/test_service.py` (или где лежат тесты
  `ROLES`/валидаторов) — `"agent"` проходит `UserCreate`/`UserUpdate`
  валидацию; `POST /auth/users {"role": "agent"}` → `201`.
- `tests/deploy/test_soarctl_users.py` — `create(role="agent")` не
  поднимает `ValueError` (расширить существующий
  `test_create_rejects_unknown_role`, добавить позитивный кейс).
- Новый параметризованный тест (или расширение
  `tests/orchestrator/api/test_actions_api.py`/`test_connectors_api.py`/
  `test_workflows_api.py`/`test_jobs_api.py`/`test_logs_api.py`) —
  пользователь с ролью `agent`: `200`/`202` на все ручки из строки
  "Стало" в таблице [S4]; `403` на `POST /auth/users`, `POST /auth/keys`,
  `GET /audit-log`, `GET /transfer/export` (или эквивалент).
- Regression: существующие роли (`viewer`, `analyst`, `service`) — их
  доступ не меняется (тесты не расширяют tuple для них, только добавляют
  `agent`); прогнать полный набор без изменений в ожиданиях для этих трёх
  ролей.
- `python -m pytest tests/deploy/test_soarctl_users.py -k role` — CLI
  проверка отдельно от orchestrator API-тестов (два процесса валидации,
  оба должны быть покрыты).

```bash
python -m pytest tests/orchestrator/ tests/soar/ tests/deploy/ -v
ruff check orchestrator/ soar/ deploy/
```

## [S7] Non-goals

- **Общий источник правды для списка ролей** — три независимых списка
  остаются независимыми (см. [S3]); унификация не входит в точечную
  правку P7.
- **Маскирование секретов (P6)** — риск реестра, не пересматривается
  этим этапом.
- **Ролевая иерархия/наследование в `require_role`** — `agent` — плоская
  роль наравне с существующими, не "admin минус N прав" на уровне
  механизма; таблица [S4] — явный список, не производная формула.
- **`PUT /prompts/user` для агента** — остаётся `_ADMIN`-only (см. [S4]).

## [S8] Success criteria

- [ ] Можно создать пользователя или API-ключ с ролью `agent` через
      `POST /auth/users` и `POST /auth/keys` (и через
      `orchestrator/auth/cli.py create-user --role agent` /
      `soarctl users create --role agent`)
- [ ] Роль `agent`: `200`/`202` на `PUT`/`DELETE`/`restore` для
      actions/connectors/workflows, `POST /jobs`, `POST
      /jobs/{id}/cancel`, `GET /logs/{job_id}`, все `_RO`-ручки
      (включая `describe`/`prompts` из Этапа 2)
- [ ] Роль `agent`: `403` на `/auth/users`, `/auth/keys`, `/audit-log`,
      `/transfer/*`, `PUT /prompts/user`
- [ ] Роли `viewer`/`analyst`/`service`/`admin` — поведение не изменилось
      (регрессия)
- [ ] Все существующие тесты проходят без изменений; новые тесты
      покрывают [S3]–[S4]
