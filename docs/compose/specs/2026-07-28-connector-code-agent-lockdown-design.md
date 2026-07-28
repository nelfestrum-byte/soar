# `PUT /connectors/{name}/code` — Literal `admin` Only (B3)

> Реализует B3 из `docs/concepts/BAGFIX_PLAN.md`. Закрывает обход P13
> (`docs/compose/specs/2026-07-27-connector-secrets-schema-design.md`) —
> роль `agent` может переписать `HIDDEN_FIELDS` в коде коннектора, которым
> сама и управляет, и обнулить редакцию секретов для этого коннектора.

## [S1] Problem

Что маскировать в `GET /config`, `/config/history[/{commit}]`,
`/config/diff` определяется `_hidden_fields_for()`
(`orchestrator/api/connectors.py:91-103`) — AST-парсингом
class-level атрибута `HIDDEN_FIELDS` в файле коннектора. Этот же файл
пишет `PUT /connectors/{name}/code` (`connectors.py:512-547`), на роли
`require_role(*_ADMIN)`, где `_ADMIN = ("admin", "agent")`
(`connectors.py:31`). `validate_connector_code()`
(`orchestrator/api/validation.py:67-74`) требует только, что где-то в
файле есть класс-наследник `BaseConnector` — не проверяет наличие,
состав или сужение `HIDDEN_FIELDS` относительно предыдущей версии.

Эксплуатация в два запроса ролью `agent`:

1. `PUT /connectors/ssh/code` — тот же класс `SSHConnector(BaseConnector)`,
   работающий конструктор, но без строки `HIDDEN_FIELDS = {"password"}`.
   Проходит валидацию (класс есть, наследование от `BaseConnector` есть).
2. `GET /connectors/ssh/config` — `_hidden_fields_for()` теперь возвращает
   пустое множество для `ssh` → `_redact_yaml()` не маскирует ничего →
   пароль в открытом виде той же роли `agent`, которая его только что
   обошла.

Смежная дыра в `PUT /config`: `_merge_hidden_fields()`
(`connectors.py:142-186`) кидает `403` при реальном изменении
hidden-поля **только если `hidden` — непустое множество**
(`save_connector_config`, `connectors.py:643-645`: `if hidden:
content = _merge_hidden_fields(...)`). При пустом `HIDDEN_FIELDS`
(после шага 1) эта ветка не выполняется вовсе — `agent` может не только
прочитать старый секрет, но и молча задать новый, минуя проверку роли,
которая для этого поля должна требовать буквально `admin`.

Модель P13 явно объявляла: "`agent` получает 403 при попытке сменить
credential" (`docs/agents/security-patterns.md`, см. D2). Контроль
инвертирован — политика (`HIDDEN_FIELDS`) хранится в данных
(файле коннектора), которыми управляет тот же субъект, для которого эта
политика должна быть ограничением.

## [S2] Solution — минимальный фикс, принят для пилота

Отозвать у `agent` право писать **код** коннектора; конфиг (`PUT
/config`) и всё остальное (`GET`/history/diff/restore, `/schema`,
`/describe`) остаются как есть — `agent` по-прежнему может видеть
код/конфиг (не-hidden значения) и обновлять сами значения полей, просто
не может переопределить, какие поля объявлены секретными.

```python
@router.put("/{name}/code")
async def save_connector_code(
    name: str, request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

Один литерал вместо `*_ADMIN` — тот же паттерн, что уже применён для
`/auth/*`, `/audit-log`, `/transfer/*`, `PUT /prompts/user`
(см. `AGENTS.md` Security patterns, P7). `restore_connector_code`
(`POST /{name}/code/restore`, `connectors.py:492-509`) остаётся на
`*_ADMIN` **сознательно, отдельным решением этого фикса**: restore
возвращает файл к одной из уже существующих в git-истории версий, не
вводит нового содержимого — `agent` не может через restore внести
версию с ослабленным `HIDDEN_FIELDS`, которой не было в истории раньше
(любая версия, где `HIDDEN_FIELDS` был сужен, уже была бы записана только
через `PUT` от `admin`, т.к. `PUT` теперь `admin`-only). Если это
рассуждение окажется неверным на этапе плана/тестов (например найдётся
путь получить в историю версию с пустым `HIDDEN_FIELDS`, минуя `PUT`) —
`restore` тоже сузить до `admin`.

`generate_connector` (`POST /connectors/generate`, `connectors.py:335-387`,
`_ADMIN`) — генерирует новый коннектор из OpenAPI-спеки; сгенерированный
код по умолчанию не имеет `HIDDEN_FIELDS` вообще (см. отдельный трек S8,
`docs/compose/specs/2026-07-28-new-connector-hidden-fields-default-design.md`)
— эта ручка не меняется в этом треке, но после S8 `agent` через
`/generate` сможет создать новый коннектор с корректно заполненным
`HIDDEN_FIELDS` (генератор проставит поля из `securitySchemes`
автоматически, не вручную) — не регрессия к этой уязвимости, т.к. `agent`
не пишет код руками в этом пути.

## [S3] Альтернатива, рассмотренная и отклонённая

**Запрет сужения `HIDDEN_FIELDS` относительно предыдущей версии файла** —
при `PUT /code`, распарсить `HIDDEN_FIELDS` старой и новой версии через
`parse_classes`, отклонить (403 или 422), если новое множество не
надмножество старого. Сохраняет `agent` возможность править код
коннектора (баг-фиксы, новые методы), не обнуляя секьюрити-политику.

Отклонено для этого трека: требует сравнения двух версий на каждом
`PUT /code` (доп. чтение старого файла + AST-парсинг обеих), не
специфицирует поведение для **нового** коннектора (`HIDDEN_FIELDS`
старой версии не существует — надо трактовать как пустое множество, тогда
first write определяет baseline, что оставляет initial-write окно для
`agent`, если он же не создаёт секрет сразу) и меняет поведение diff'а
между версиями, а не просто RBAC на ручке. Дороже, отдельная спека, если
понадобится вернуть `agent` право редактировать код коннекторов — **не в
этот трек**.

## [S4] Testing Strategy

`tests/orchestrator/api/test_connectors.py`:

- **Новый** `test_agent_forbidden_from_connector_code_write` —
  `PUT /connectors/{name}/code` от роли `agent` → `403`. Регрессионно
  воспроизводит эксплуатацию из [S1]: попытка переписать существующий
  коннектор с `HIDDEN_FIELDS` без этого атрибута теперь блокируется на
  уровне роли, до парсинга содержимого.
- **Regression** `test_admin_can_write_connector_code` — `admin`
  по-прежнему может писать код коннектора, весь текущий флоу (валидация +
  git commit + audit record) не ломается.
- Убедиться, что существующие тесты на `PUT /config` (merge-on-write,
  403 на изменение hidden-поля ролью `agent`) остаются зелёными без
  изменений — этот трек их не трогает.
- Опционально: тест, что после [S2] эксплуатация из [S1] (два запроса
  подряд) больше не проходит — первый же запрос (`PUT /code` без
  `HIDDEN_FIELDS` от `agent`) уже `403`, до второго запроса дело не
  доходит.

## [S5] Success Criteria

- [ ] `PUT /connectors/{name}/code` от роли `agent` — `403`, от `admin` —
      работает как раньше (валидация, git commit, audit record не
      регрессируют)
- [ ] `agent` не может обнулить/сузить `HIDDEN_FIELDS` коннектора ни одним
      доступным ему путём
- [ ] `docs/agents/security-patterns.md` обновлён: «`agent` получает 403
      при попытке сменить credential» дополняется «и при попытке
      переписать код коннектора» (см. D2 — правится вместе с этим фиксом)
