# Audit-Log Job Creation (`POST /jobs`, `POST /webhooks/{name}`) (S4)

> Реализует S4 из `docs/concepts/BAGFIX_PLAN.md`. Запуск workflow —
> самое мутирующее действие в системе (может блокировать IP, отключать
> учётку, удалять файл — зависит от того, что делает конкретный
> workflow), и единственное, что сегодня не пишет `audit_log`, вопреки
> заявлению `AGENTS.md` "из каждого мутирующего роута".

## [S1] Problem

`orchestrator/api/jobs.py::create_job()` (`jobs.py:23-38`) создаёт
`WorkflowJob` через `job_manager.enqueue()`, возвращает `job.to_dict()`
— без единого вызова `audit_service.record()`. Единственная audit-запись
во всём файле — `job.cancel` в `cancel_job()` (`jobs.py:71-86`), которая
уже принимает `user: CurrentUser`/`db: AsyncSession` как параметры.
`create_job()` сегодня не принимает ни то, ни другое — только
`body: JobRequest, request: Request`, полагаясь на router-level
`dependencies=[Depends(require_role(*_RW))]` (`jobs.py:23`), который не
даёт доступа к `CurrentUser`/DB-сессии внутри тела функции.

`orchestrator/api/webhooks.py::handle_webhook()` (`webhooks.py:11-43`) —
без auth вообще (JWT/RBAC), только `X-Webhook-Token` per-workflow
(`meta.token`, сверяется `secrets.compare_digest`). Нет `CurrentUser` в
принципе — вебхук не аутентифицирован через обычный auth-механизм,
`get_current_user`/`require_role` не участвуют в этом роуте вовсе.
`audit_service.record()` требует `user: CurrentUser` — нет естественного
актора для этого вызова.

## [S2] Solution

### [S2.1] `POST /jobs` — обычный actor-based audit record

```python
@router.post("", status_code=202)  # снять dependencies=[Depends(require_role(*_RW))]
async def create_job(
    body: JobRequest, request: Request,
    user: CurrentUser = Depends(require_role(*_RW)),
    db: AsyncSession = Depends(get_db),
):
    job_manager = request.app.state.job_manager
    try:
        job = await job_manager.enqueue(
            workflow_name=body.workflow_name, context=body.context, triggered_by="user",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Workflow not found") from None
    except WorkflowDisabledError:
        raise HTTPException(status_code=409, detail="Workflow is disabled") from None
    except Exception:
        raise HTTPException(status_code=409, detail="Failed to enqueue job") from None

    await audit_service.record(
        db, user=user, action="job.create", resource_type="job",
        resource_id=job.id, request=request,
        detail={"workflow_name": job.workflow_name},
    )
    return job.to_dict()
```

(меняем `dependencies=[Depends(require_role(*_RW))]` на явный
`user: CurrentUser = Depends(require_role(*_RW))` параметр — тот же
паттерн, что уже применён в `cancel_job()` ниже в этом же файле; сама
RBAC-проверка не меняется, роль всё ещё требует `*_RW`, просто теперь
доступна внутри тела функции.)

`detail` фиксирует `workflow_name` (уже в `resource_id`/`job.to_dict()`
и так, но для консистентности с остальными `record()`-вызовами, которые
кладут ключевые параметры мутации в `detail` явно) — **не** кладёт
`body.context` целиком: контекст запуска может содержать произвольные
пользовательские данные (см. смежный M12 — `job.context` и так уже
хранится в БД и виден `viewer`-роли через `GET /jobs`, но `audit_log` —
отдельная поверхность с собственной RBAC (`admin`-only), дублировать в
неё то, что уже есть в `job_store`, не даёт дополнительной ценности и
увеличивает объём `detail` без нужды).

### [S2.2] `POST /webhooks/{name}` — синтетический actor

Решение по формату актора (явно требуется до реализации, per план):
вебхук — не `user`/`service` (оба типа сегодня определены в
`CurrentUser.type`, см. `orchestrator/auth/dependencies.py:11-16`, и в
`AuditLog.actor_type` docstring, `orchestrator/audit/models.py:14`), а
третий тип, **`"webhook"`** — расширяет уже существующий informal enum
(колонка `String(16)`, не настоящий SQL enum — добавление нового
строкового значения не требует миграции):

```python
# orchestrator/api/webhooks.py
_WEBHOOK_ACTOR = CurrentUser(id=0, role="service", type="webhook", username="")

async def handle_webhook(workflow_name: str, request: Request, db: AsyncSession = Depends(get_db)):
    job_manager = request.app.state.job_manager
    meta = job_manager.get_meta(workflow_name)
    ...
    try:
        job = await job_manager.enqueue(
            workflow_name=workflow_name, context={"payload": body}, triggered_by="webhook",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Workflow not found or disabled") from None
    except Exception:
        raise HTTPException(status_code=409, detail="Failed to enqueue job") from None

    actor = CurrentUser(id=0, role="service", type="webhook", username=f"webhook:{workflow_name}")
    await audit_service.record(
        db, user=actor, action="job.create", resource_type="job",
        resource_id=job.id, request=request,
        detail={"workflow_name": workflow_name, "triggered_by": "webhook"},
    )
    return {"job_id": job.id}
```

`actor_name` (`audit_service.record` строит его из `user.username or
str(user.id)`) станет `"webhook:{workflow_name}"` — узнаваемо в
`audit_log` без join'а на что-либо ещё (webhook-акторы не имеют
username/id в таблице `users` — это не пользователь системы, а внешний
триггер). `actor_id=0` — тот же конвенционный "системный" id, что уже
использует анонимный admin при отключённом auth
(`get_current_user`, `dependencies.py:29`, `CurrentUser(id=0, ...)`) —
не путается с реальными пользователями (id автоинкремент с 1).

`db: AsyncSession = Depends(get_db)` добавляется в сигнатуру
`handle_webhook` — сегодня роут не открывает DB-сессию вообще; `GET
/webhooks` не существует как отдельный read-роут, только `POST`, так что
это не затрагивает случай "лишний `Depends(get_db)` для JWT-запросов без
DB" (см. `AGENTS.md` Code rules — то правило про `get_current_user`,
`handle_webhook` не использует `get_current_user`, там нет конфликта).

Невалидный токен (403, `webhooks.py:22-27`) и disabled workflow (409,
`webhooks.py:29-30`) — **не** пишут audit-запись, только
`logger.warning("webhook.invalid_token")` (уже есть, не мутация, ничего
не создано). Audit-запись пишется только на успешный `enqueue()`,
симметрично `POST /jobs`.

## [S3] Testing Strategy

`tests/orchestrator/api/test_jobs.py`:

- **Новый** `test_create_job_writes_audit_log` — `POST /jobs` с валидным
  `workflow_name`, проверить запись `job.create` в `audit_log` с
  `resource_id == job["id"]`, `detail.workflow_name` совпадает.
- **Regression**: существующие тесты 404/409 (workflow not found/
  disabled) не должны начать писать audit-запись — только успешный
  enqueue пишет.

`tests/orchestrator/api/test_webhooks.py`:

- **Новый** `test_webhook_success_writes_audit_log` — валидный токен,
  enabled webhook workflow → `audit_log` содержит запись с
  `actor_type == "webhook"`, `actor_name == f"webhook:{workflow_name}"`,
  `action == "job.create"`.
- **Regression**: невалидный токен (403) и disabled workflow (409) не
  пишут audit-запись — тест на количество записей до/после (0 новых).

## [S4] Success Criteria

- [ ] `POST /jobs` пишет `job.create` с `workflow_name` в `detail` и
      `job_id` в `resource_id`, RBAC не меняется
- [ ] `POST /webhooks/{name}` пишет `job.create` с синтетическим
      `actor_type="webhook"` только на успешный enqueue, не на 403/409
- [ ] `job.context`/`body.context` целиком не попадает в `detail`
      audit-записи (см. смежный M12 — не дублировать проблему в новую
      поверхность)
- [ ] `AGENTS.md` "Audit trail" перестаёт содержать неверное общее
      заявление без исключений (см. D3, правится вместе с этим треком)
