# `/transfer/export` + `/transfer/import` Hardening (S3)

> Реализует S3 из `docs/concepts/BAGFIX_PLAN.md`. `POST /transfer/export`
> отдаёт секреты без редакции и без audit-записи — тот же периметр,
> который P13 (`docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`)
> закрывал во всех остальных read-ручках, остался открытым здесь.
> `/import` дополнительно обходит P1 (валидация кода) и P8 (git-история).

## [S1] Problem

`orchestrator/api/transfer.py` — весь роутер на
`dependencies=[Depends(require_role("admin"))]`
(`transfer.py:15`), но внутри:

- `export_entities()` (`transfer.py:18-82`) пишет `{name}.yml` каждого
  коннектора в архив как есть (`zf.write(yml_file, f"connectors/
  {entry.name}/config.yml")`, `transfer.py:38-39`) — без вызова
  `_redact_yaml`/`_hidden_fields_for`
  (`orchestrator/api/connectors.py:91-121`). P13 объявлял модель
  "write-only секреты — прочитать через API нельзя никому, включая
  admin" (см. `connector-secrets-schema-design.md` [S2].4); экспорт —
  такой же API-путь чтения содержимого файла, просто в виде ZIP вместо
  JSON, и эта модель для него не действует. `admin`, дёрнувший
  `/export`, получает все пароли/api-ключи всех коннекторов одним
  запросом.
- Ни `export_entities`, ни `import_entities` не вызывают
  `audit_service.record()` ни разу — выгрузка **всех** credential'ов
  системы (или их массовая перезапись при `/import?force=true`) не
  оставляет следа в `audit_log`. Каждый другой мутирующий/чувствительный
  роут в проекте это делает (см. `AGENTS.md` Audit trail).
- `import_entities()` (`transfer.py:85-205`) пишет `connectors/{name}/
  {name}.py`, `actions/{name}.py`, `workflows/{name}.py` из архива
  напрямую на диск (`shutil.move`, `transfer.py:160,179,190`), минуя
  `validate_connector_code`/`validate_action_code`/`validate_workflow_code`
  (`orchestrator/api/validation.py`) — обход P1: невалидный/не
  соответствующий ожидаемому классу-наследнику код проходит на диск, а
  падает уже при следующей попытке загрузить реестр
  (`WorkflowRegistry`/`ActionsRegistry`/`ConnectorRegistry`), с менее
  понятной ошибкой, чем `422` в момент записи.
- `import_entities()` не коммитит импортированные файлы в git вообще —
  ни один вызов `git.commit(...)`. История/diff/restore (P8) не видят
  импортированные версии — `git log` для файла, появившегося через
  `/import`, начинается с первого **ручного** редактирования через `PUT`,
  не с момента реального появления файла в системе. Откатить импорт
  через `restore` тоже нельзя — restore работает по commit-хэшам,
  которых для этих файлов не существует.

## [S2] Solution

### [S2.1] Редакция в `/export`

Переиспользовать `_redact_yaml`/`_hidden_fields_for` из
`orchestrator/api/connectors.py` (не дублировать — те же функции,
импортировать):

```python
from orchestrator.api.connectors import _hidden_fields_for, _redact_yaml
```

В цикле по коннекторам (`transfer.py:31-39`), перед `zf.write(yml_file,
...)`: прочитать содержимое, редактировать, писать в архив строкой, не
файлом напрямую —

```python
if os.path.exists(yml_file):
    with open(yml_file, encoding="utf-8") as f:
        content = f.read()
    hidden = _hidden_fields_for(config, entry.name)
    zf.writestr(f"connectors/{entry.name}/config.yml", _redact_yaml(content, hidden))
    connectors.append(entry.name)
```

(`zf.write` берёт файл с диска напрямую; редактированный контент нужно
класть через `zf.writestr` на уже прочитанную и обработанную строку —
меняется механика записи в архив для этой ветки, не для `.py`-файлов
коннекторов/actions/workflows, которые не содержат секретов и
продолжают идти через `zf.write` как раньше.)

Экспорт становится **write-only-совместимым**: секреты, которые нельзя
прочитать через `GET /config`, нельзя прочитать и через `/export`. Это
намеренно ограничивает полезность `/export` как инструмента бэкапа —
восстановленный через `/import` коннектор получит `********` вместо
реальных значений hidden-полей и потребует их переввода вручную через
`PUT /config` (та же семантика merge-on-write из P13 — `********`
на wire трактуется как "не менять", но при **imported** файле, где
предыдущего значения на диске ещё нет, `_merge_hidden_fields` не сможет
подставить старое значение и должен либо оставить поле отсутствующим,
либо потребовать заполнения; это поведение существующей функции,
не меняется этим треком — задокументировать как известное ограничение
экспорта/импорта, не отдельный баг).

### [S2.2] `audit_service.record()` в обоих роутах

```python
@router.post("/export")
async def export_entities(request: Request, user: CurrentUser = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    ...
    await audit_service.record(
        db, user=user, action="transfer.export", resource_type="transfer",
        resource_id=filename, request=request,
        detail={"connectors": connectors, "actions": actions, "workflows": workflows},
    )
    return StreamingResponse(...)
```

(роут сегодня не принимает `user`/`db` явно — полагается только на
router-level `dependencies=[Depends(require_role("admin"))]`, который не
даёт доступа к `CurrentUser` внутри функции; добавить оба параметра явно,
как уже сделано во всех остальных мутирующих роутах проекта.)

```python
@router.post("/import")
async def import_entities(
    request: Request, file: UploadFile,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ...
    await audit_service.record(
        db, user=user, action="transfer.import", resource_type="transfer",
        resource_id=file.filename or "", request=request,
        detail={"imported": imported, "conflicts_overwritten": len(conflicts) if force else 0},
    )
    return {...}
```

`detail` пишет только **имена** импортированных/экспортированных
сущностей — не содержимое файлов (та же осторожность, что и во всех
остальных `audit_service.record()` вызовах в проекте, см. `AGENTS.md`
Audit trail: "не стоит логировать секреты в теле").

Ранний `return` при конфликтах без `force`
(`transfer.py:143-148`) — **не** пишет audit-запись: ничего не
изменилось на диске, это read-only preflight-ответ, не мутация.

### [S2.3] `/import` — валидация кода перед записью

Для каждого извлечённого `.py`-файла — вызвать соответствующий
`validate_*_code` **до** `shutil.move` на целевой путь (сейчас `zf.extract`
+ `shutil.move` происходят без промежуточной проверки):

```python
code_path = f"connectors/{name}/code.py"
if code_path in zf.namelist():
    content = zf.read(code_path).decode("utf-8")
    validate_connector_code(content)   # raises HTTPException(422) on failure
    ...
```

Аналогично `validate_action_code(content, name)` для
`actions/{name}.py` и `validate_workflow_code(content)` для
`workflows/{name}.py`. Валидация — **до** физической записи любого файла
из архива: если хотя бы одна сущность в манифесте не проходит
валидацию, весь `/import` должен откатиться, ничего не записав частично
(на этапе плана — либо провалидировать все сущности архива первым
проходом, прежде чем начинать `shutil.move` кого-либо, либо писать во
временную директорию и переносить атомарно только после полной
валидации; первый вариант проще и достаточен для этого фикса).

### [S2.4] `/import` — git commit после записи

После успешной записи каждого файла (в существующих циклах
`transfer.py:150-191`) — `await git.commit(relative_path, f"Import
{type} {name}", author_name=author_name, author_email=author_email)`,
тем же паттерном `author_name, author_email = audit_service.git_author(user)`,
что используют все остальные write-роуты. Ошибка `git.commit()`
(`RuntimeError`, известный "nothing to commit" case — не актуален здесь,
импортированный файл всегда новый или изменённый контент, но
теоретически возможен, если импортируется байт-в-байт идентичный уже
существующему файлу при `force=true`) — не должна прерывать весь импорт
на середине; собрать предупреждения в ответ, аналогично
`{"status": "saved", "commit": "", "warning": str(e)}` в
`connectors.py`.

## [S3] Testing Strategy

`tests/orchestrator/api/test_transfer.py`:

- **Новый** `test_export_redacts_hidden_fields` — создать коннектор с
  `HIDDEN_FIELDS = {"password"}` и реальным значением в `{name}.yml`,
  вызвать `/export`, распаковать архив, убедиться, что `config.yml`
  внутри содержит `********`, не реальный пароль.
- **Новый** `test_export_writes_audit_log` — вызвать `/export`,
  проверить запись `transfer.export` в `audit_log` с корректным
  `actor_id`/`resource_type`.
- **Новый** `test_import_writes_audit_log` — аналогично для
  `transfer.import`.
- **Новый** `test_import_rejects_invalid_workflow_code` — архив с
  `workflows/{name}.py`, не содержащим класс-наследник
  `BaseWorkflow`/... → `422`, ничего не записано на диск (проверить,
  что директория/файл не появились).
- **Regression**: существующие тесты на conflict-detection
  (`force=true`/`false`) и на успешный round-trip export→import остаются
  зелёными — редакция/audit/валидация/commit не меняют формат
  манифеста или структуру архива для валидных сущностей.
- Тест, что preflight-ответ с конфликтами (без `force`) **не** пишет
  audit-запись (различие "показал конфликты" vs "реально импортировал").

## [S4] Success Criteria

- [ ] Экспортированный `{name}.yml` внутри архива содержит `********`
      вместо значений `HIDDEN_FIELDS`, той же функцией редакции, что и
      остальной API (не дублирующей копией)
- [ ] `/export` и `/import` пишут `audit_log` с именами
      экспортированных/импортированных сущностей, без содержимого файлов
- [ ] `/import` отклоняет (`422`) любую сущность с невалидным
      кодом/несоответствующим классом до того, как что-либо записано на
      диск
- [ ] `/import` коммитит каждый импортированный файл в git от имени
      актора; история/diff/restore видят импортированные версии
- [ ] Preflight-ответ с конфликтами (без `force`) не создаёт audit-запись
- [ ] `docs/agents/security-patterns.md`/`AGENTS.md` обновлены: P13
      write-only модель распространяется на `/transfer/export`, audit
      trail покрывает `/transfer/*` (см. D1/D3, правятся вместе с этим
      треком)
