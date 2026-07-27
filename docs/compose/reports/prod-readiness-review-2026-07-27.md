# Pre-production code review — 2026-07-27 (v0.12 / AGENTS.md v0.13)

Скоуп: `orchestrator/`, `soar/` (без коннекторов, кроме `base.py`), `alembic/`,
конфиги деплоя. Вне скоупа по указанию заказчика: `ui/`, тела коннекторов,
тесты (кроме прогона).

Проверялось: (1) соответствие логики концептам `docs/concepts/UPGRADE.md` и
`UPGRADE-v2.md`, логические дыры критичные для прода; (2) безопасность;
(3) соответствие агентских файлов реальности.

**Вывод: к пилоту готовы после закрытия 4 блокеров (B1–B4).** Архитектурных
дыр и потребности в крупном рефакторинге не найдено — все блокеры это
точечные правки в пределах одного-двух файлов. Обоснование — в конце.

---

## A. Блокеры (чинить до включения на живой инфре)

### B1. Деактивация пользователя не выкидывает его из системы — refresh-токен живёт вечно

`orchestrator/auth/service.py:63-93` (`rotate_refresh_token`),
`orchestrator/auth/router.py:57-72` (`POST /auth/refresh`).

`authenticate_user()` фильтрует по `is_active` — но только на `/auth/login`.
`rotate_refresh_token()` проверяет `revoked_at` и `expires_at` **и не смотрит
`User.is_active`**. Каждый вызов `/auth/refresh` выдаёт новый access-токен и
новый refresh-токен на 7 дней. Итог:

- `PATCH /auth/users/{id} {is_active: false}` и
  `python -m orchestrator.auth.cli deactivate-user` **не отзывают доступ**.
  Уволенный сотрудник / скомпрометированный агент продолжает работать
  бессрочно, пока сам обновляет токен раз в неделю.
- Ни один код-путь не удаляет/не помечает `revoked_at` у refresh-токенов при
  деактивации или смене роли.

Это же ломает recovery-путь, на который опирается принятый риск P15
(`UPGRADE-v2.md`): «recovery через CLI» подразумевает, что деактивация
работает. Она не работает.

**Фикс:** в `rotate_refresh_token` проверять `user.is_active` (вернуть `None`,
если False) + в `update_user()` при `is_active=False` или смене роли ставить
`revoked_at` всем живым refresh-токенам этого пользователя. ~15 строк.

### B2. `GET /connectors/{name}/config/diff` отдаёт секреты открытым текстом роли `viewer`

`orchestrator/api/connectors.py:34` (`_DIFF_KV_RE`), `124-139` (`_redact_diff`),
`592-601` (роут на `_RO`).

Регулярка требует, чтобы строка начиналась с `+` или `-`:
`^([+-])(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$`. В unified diff **неизменённые
строки — контекст с ведущим пробелом**. Воспроизведено:

```
@@ -1,4 +1,4 @@
 instances:
   x1:
-    base_url: https://a
+    base_url: https://b
     password: SUPERSECRET      ← контекстная строка, регулярка не матчит
```

Любая правка соседнего поля (`base_url`, `timeout`, что угодно) выводит
неизменённый `password`/`api_key`/`token` в контекст diff'а, и `_redact_diff`
его пропускает. Роль `viewer` читает пароль в открытом виде.

Это ровно та дыра, которую закрывал P13, — она осталась открытой через
третий из трёх редактируемых эндпоинтов. `docs/agents/security-patterns.md`
утверждает обратное («значения hidden-полей маскируются в `GET /config`,
`/config/history[/{commit}]`, `/config/diff` для всех ролей»).

**Фикс:** матчить и контекстные строки тоже — `^([+\- ])(\s*)(key):\s*(.*)$`,
плюс тест на diff с неизменённым hidden-полем.

### B3. Роль `agent` обходит редакцию секретов, переписав `HIDDEN_FIELDS`

`orchestrator/api/connectors.py:31` (`_ADMIN = ("admin", "agent")`), `91-104`
(`_hidden_fields_for`), `512-547` (`PUT /{name}/code`),
`orchestrator/api/validation.py:67-74` (`validate_connector_code`).

Что маскировать — определяется AST-разбором `HIDDEN_FIELDS` **в том же файле
коннектора, который `agent` имеет право перезаписать**. `validate_connector_code`
требует только «класс, наследующий `BaseConnector`». Эксплуатация в два
запроса:

1. `PUT /connectors/ssh/code` — тот же класс без `HIDDEN_FIELDS`;
2. `GET /connectors/ssh/config` — `hidden` пустой, пароль/ключ в ответе.

`PUT /config` с merge-on-write тоже отваливается: `hidden` пустой → проверка
`user.role != "admin"` не выполняется вовсе, `agent` перезаписывает
credential напрямую.

P13 явно проектировался так, чтобы `agent` получал `403` на секретах
(«hidden-поля меняет только буквально `admin`, не `_ADMIN`-tuple»). Контроль
обходится, потому что политика хранится в данных, которыми управляет
контролируемый субъект.

**Фикс (минимальный, без редизайна):** вынести `PUT /connectors/{name}/code`
из `_ADMIN` в литеральный `("admin",)` — как уже сделано для `/transfer/*` и
`PUT /prompts/user`. Агент теряет возможность править коннекторы (не
workflows/actions), что соответствует духу P13. Альтернатива, если правка
коннекторов агентом нужна: запретить сужение `HIDDEN_FIELDS` относительно
предыдущей версии файла — дороже, оставить на после пилота.

### B4. За nginx все клиенты выглядят одним IP — rate limit и audit-log бесполезны

`deploy/prod/nginx.conf:15-17` (ставит `X-Real-IP`/`X-Forwarded-For`),
`orchestrator/core/net.py:9-17`, `deploy/prod/config.yaml.template` и
`deploy/stage/config.yaml` (**нет секции `server.trusted_proxies`** → дефолт
`[]` из `orchestrator/config.py:76`).

`resolve_client_ip()` доверяет заголовкам только от `trusted_proxies`. В
проде список пуст, значит для всего трафика через nginx `client_ip` = IP
контейнера nginx. Последствия:

- **Логин-лимитер 5 req/60s становится глобальным**: один клиент, промахнувшийся
  паролем 5 раз, блокирует логин **всем пользователям** на минуту. Тривиальный
  перманентный DoS аутентификации (`orchestrator/main.py:267,279-282`).
- Общий лимит 120 req/60s — тоже общий на всех, а не на клиента.
- `AuditLog.client_ip` и `client_ip` в access-логе одинаковы для всех записей —
  атрибуция инцидента по IP невозможна. Для системы, которая пишет audit trail
  под комплаенс, это обесценивает поле.

**Фикс:** добавить `server.trusted_proxies` в оба шаблона деплоя (IP/подсеть
контейнера nginx или docker-сети). Правка конфига, не кода.

---

## B. Существенные, но не блокирующие пилот

### S1. P12 закрыт формально: `HttpClient` не используется ни одним call-site и структурно не может быть использован

- `grep` по `soar/`: единственные упоминания `http_client` — сам модуль,
  `soar/tools/__init__.py` и `soar/runner.py`. Ни один коннектор его не
  вызывает; `soar/actions/` вообще пуст (только `__init__.py`).
- Все 24 коннектора синхронные и используют `requests` напрямую
  (`grep "import requests" soar/connectors/` — 10 файлов, остальные через SDK).
  `HttpClient.get_json`/`post_json` — `async def`. Из синхронного
  `_connect_impl`/метода коннектора их не вызвать без `asyncio.run()`.

То есть проблема, ради которой писался P12 («TI-запросы без кэша и без
единого лога»), в проде остаётся ровно в том же виде. Тул есть, адаптации нет.

Не блокер: коннекторы по решению заказчика правятся на месте в проде. Но
считать P12 закрытым нельзя — при первой же миграции коннектора на `HttpClient`
всплывёт async/sync-барьер и понадобится синхронная обёртка.

### S2. `from soar.tools import http_client` не работает — порядок инициализации в раннере

`soar/runner.py`: `actions.init()` / `connectors.init()` — строки 36-37,
`tools.http_client = _build_http_client(config)` — строка 63. Модули actions и
коннекторов импортируются **раньше**, чем синглтон переприсваивается. Любой
модуль, сделавший `from soar.tools import http_client` на верхнем уровне,
навсегда захватит дефолтный экземпляр без конфига (без Redis-кэша, с
`default_ttl` по умолчанию).

При этом `soar/tools/__init__.py:4-6` прямо обещает обратное: «actions can
always `from soar.tools import http_client`». Документация в коде расходится с
поведением кода.

**Фикс:** перенести строку 63 выше `workflows.init()`/`connectors.init()`/
`actions.init()`, либо сделать `http_client` ленивым (module `__getattr__`).

### S3. Секреты коннекторов утекают через `POST /transfer/export` без редакции и без audit-записи

`orchestrator/api/transfer.py:38-39` — `{name}.yml` кладётся в zip как есть.
Роут `admin`-only, но модель P13 объявлена как «write-only секреты, прочитать
через API нельзя **никому, включая admin**». Экспорт — тот же API, редакции
там нет. Плюс ни `/export`, ни `/import` не пишут `audit_log` и не коммитят в
git — выгрузка всех credential'ов системы не оставляет следа.

`/import` дополнительно не прогоняет код через `validate_*_code` (обход P1) и
не коммитит импортированные файлы, так что git-история и rollback (P8) для них
недоступны.

### S4. Запуск workflow не пишется в audit-log

`orchestrator/api/jobs.py:23-38` (`POST /jobs`) и
`orchestrator/api/webhooks.py:11-43` — записи `audit_service.record()` нет.
Аудируется только `job.cancel`. Между тем запуск workflow — самое
«мутирующее» действие в системе: блокировка IP, отключение учётки, удаление
файла. AGENTS.md утверждает, что `record()` вызывается «из каждого
мутирующего роута».

### S5. Логи джобов не чистятся никогда

`jobs.retention_days` (`orchestrator/store/sql_job_store.py:102-115`) удаляет
строки в БД, но файлы `/var/log/soar/jobs/<workflow>/<job_id>.log` не трогает
ничто в кодовой базе. Хуже: удаление строки уничтожает `log_path`, после чего
файл становится осиротевшим навсегда. На проде с `retention_days: 90` и
регулярными расследованиями это гарантированное заполнение диска.

### S6. Партиальный индекс из спеки P14 не создаётся на штатной установке прода

`alembic/versions/42fbd47b0d46_add_workflow_jobs_pending_index.py` создаёт
`ix_workflow_jobs_pending_triggered_at`. Модель его не декларирует (комментарий
в `orchestrator/store/models.py:10-14` это фиксирует осознанно). Штатная
последовательность прода из AGENTS.md — `soarctl up && soarctl migrate --fresh`,
а `--fresh` = `alembic stamp head` (`deploy/soarctl_lib/migrate.py:26-27`),
который **не выполняет DDL**. Значит на любой свежей проде индекса нет.
Не критично (на `status` есть обычный индекс), но заявленная в спеке
оптимизация не поставлена.

Смежное: миграции используют литеральное `workflow_jobs`, игнорируя
`database.table_prefix`. Для стенда `deploy/stage` (`table_prefix: "stage_"`)
`alembic upgrade head` работает не с той таблицей, что приложение.

### S7. Тест-сьют на `main` красный

`python -m pytest tests/` — `1 failed, 648 passed, 1 skipped`
(+5 модулей не собираются из-за отсутствующих опциональных зависимостей
`pymisp`/`pymysql`/`shodan`/`impacket`/`pywinrm` — это окружение, не код).

Падает `tests/soar/tools/test_openapi.py::test_generate_config` — тест ждёт
имя инстанса `my_api:`, код (`soar/tools/openapi.py:227-232`) генерирует
`MyApiConnector1:`. Расхождение кода и теста не разрешено; надо решить, какое
поведение правильное, и привести второе к первому.

### S8. Сгенерированные и созданные через API коннекторы не получают `HIDDEN_FIELDS`

`CONNECTOR_TEMPLATE` (`orchestrator/api/connectors.py:50-64`) и
`OpenAPIGenerator` (`soar/tools/openapi.py`) не эмитят `HIDDEN_FIELDS`, при
этом `_generate_config` кладёт в yml `api_key`/`token`/`password`
(`openapi.py:239-248`). Все 24 встроенных коннектора объявление имеют
(проверено grep'ом), а любой **новый** коннектор — нет. Редакция P13 —
opt-in, и дефолт у неё «не редактировать». Это тот путь, которым коннекторы и
будут создаваться в проде.

**Фикс:** добавить `HIDDEN_FIELDS: ClassVar[set[str]] = set()` в шаблон и
заполнять его в генераторе именами полей из `securitySchemes`.

---

## C. Мелкое (можно чинить по ходу пилота)

| # | Что | Где |
|---|-----|-----|
| M1 | `HttpClient` логирует полный URL с query-string — при переходе TI-коннекторов на него API-ключи вида `?apikey=...` попадут в лог | `soar/tools/http_client.py:145,159` |
| M2 | `RateLimiter._requests` — `defaultdict`, ключи-IP никогда не удаляются, растёт неограниченно | `orchestrator/main.py:225-237` |
| M3 | `GET /connectors/preview` вызывает `preview_spec(Request, body)` — передаёт **класс** `Request`, а не инстанс; работает только потому, что аргумент не используется | `orchestrator/api/connectors.py:332` |
| M4 | SSRF-guard резолвит DNS, затем httpx резолвит повторно — окно DNS-rebinding (смягчено `follow_redirects=False`) | `connectors.py:290-315`, `http_client.py:80-105` |
| M5 | `stream_log` открывает `job.log_path` без проверки существования → 500 внутри SSE-генератора | `orchestrator/api/logs.py:39` |
| M6 | `handle_webhook`: `await request.json()` без try → 500 на невалидном JSON от внешней системы | `orchestrator/api/webhooks.py:32` |
| M7 | `ConcurrencyPolicy.QUEUE` + `SQLQueue` = вечный цикл: `pop()` уже ставит `RUNNING`, а busy-wait ждёт «нет RUNNING». Латентно — `load_workflow_metas` никогда не назначает `QUEUE` | `worker.py:47-49`, `sql_queue.py:56-60` |
| M8 | `decode_access_token` → `int(payload["sub"])` без защиты: токен, подписанный тем же ключом, но без `sub`, даёт 500 вместо 401 | `auth/dependencies.py:42` |
| M9 | `soar/connectors/irp/` — пустая директория (только `__pycache__`), светится в `GET /connectors` как коннектор без кода | — |
| M10 | Redis остаётся в `deploy/prod/docker-compose.yml` после перехода на `queue.backend: sql` — неиспользуемый компонент в проде | `deploy/prod/docker-compose.yml:3-13` |
| M11 | Прод публикует `8000:8000` без TLS; JWT и пароли ходят открытым текстом, если снаружи нет своего LB. Нужен явный пункт runbook'а | `deploy/prod/docker-compose.yml:33-34` |
| M12 | `job.context` (payload вебхука целиком) хранится в БД и отдаётся роли `viewer` через `GET /jobs` | `models/job.py:38-51`, `api/jobs.py:41` |

---

## D. Соответствие агентских файлов реальности

Файлы в целом точны — расхождения точечные, все следствие пунктов выше:

| Утверждение | Реальность |
|---|---|
| `security-patterns.md`: «значения hidden-полей маскируются в `GET /config`, `/config/history[/{commit}]`, `/config/diff` **для всех ролей, включая admin** — секреты write-only, прочитать через API нельзя никому» | Неверно дважды: `/config/diff` отдаёт неизменённые секреты в контексте (B2); `POST /transfer/export` отдаёт весь yml без редакции (S3) |
| `security-patterns.md`: «`agent` получает `403` при попытке сменить credential» | Обходится переписыванием `HIDDEN_FIELDS` через `PUT /connectors/{name}/code` (B3) |
| AGENTS.md: audit записывается «из каждого мутирующего роута» | Нет для `POST /jobs`, `POST /webhooks/{name}`, `/transfer/export`, `/transfer/import` (S3, S4) |
| AGENTS.md: «`soar/tools/http_client.py` (HttpClient singleton)»; `soar/tools/__init__.py`: «actions can always `from soar.tools import http_client`» | Такой импорт даёт неинициализированный экземпляр (S2); call-site'ов нет вовсе (S1) |
| AGENTS.md File map: «`soar/actions/__init__.py` — ActionsRegistry — автообнаружение actions» | Формально верно, но `soar/actions/` пуст — actions в поставке нет. `UPGRADE-v2.md` P12 говорит про «actions для VT, AbuseCh, …», которых не существует; это коннекторы |
| `UPGRADE-v2.md` P15: recovery от self-lockout — деактивация/CLI | Деактивация не отзывает refresh-токены (B1), т.е. и сам механизм деактивации не работает как заявлено |
| `known-limitations.md` #8 (мультиинстансность) | Миграция `42fbd47b0d46` ссылается на «known-limitation #9» — номер после перенумерации в v0.12 не существует |
| `UPGRADE-v2.md` P14, спека [S5]: партиальный индекс | На штатной установке прода (`migrate --fresh` = `stamp head`) не создаётся (S6) |
| `UPGRADE-v2.md` P17: «`config.yaml.template` содержит плейсхолдер `auth.cors_origins`» | Подтверждено — сделано. Но `server.trusted_proxies` в том же шаблоне отсутствует, хотя nginx там же ставит `X-Real-IP` (B4) |

Что подтвердилось как корректно реализованное: P1 (`validate_*_code` в PUT),
P2 (traceback в `WorkflowResult.traceback` → `runner.main()` → `result_error`),
P8 (history/diff/restore на всех трёх сущностях), P9 (токен из
`orchestrator_state.yaml` приоритетнее классового), P7 (роль `agent` заведена,
`/transfer/*`, `/auth/*`, `/audit-log`, `PUT /prompts/user` — литеральный
`admin`), P16 (`git diff --cached --quiet` вместо string-match),
P14 (`SQLQueue` — атомарный claim, `FOR UPDATE SKIP LOCKED` на Postgres;
orphan-PENDING из P14 действительно исчез, т.к. очередь и стор — одна таблица),
P13 в части `GET /config` и `/config/history` (там редакция работает).

---

## E. Вывод по готовности

Критерий заказчика: нет проблем безопасности, архитектурных дыр и потребности
в крупном рефакторинге.

**Архитектурных дыр нет.** Разделение orchestrator/soar, subprocess-изоляция
раннера, очередь поверх одной таблицы вместо второго источника правды,
AST-интроспекция без импорта, git как хранилище версий — всё это внутренне
согласовано и держит нагрузку пилота. Принятые риски P5/P6/P10/P11/P15
задокументированы честно и остаются приемлемыми для пилота.

**Крупный рефакторинг не требуется.** Все четыре блокера — правки в пределах
одного-двух файлов: две проверки в `auth/service.py`, один символ в регулярке
`_redact_diff`, один tuple в декораторе роута, одна секция в двух yaml.

**Проблемы безопасности есть, и они блокирующие в текущем виде.** B1 (деактивация
не работает) и B2 (секреты в diff для `viewer`) — это не теоретические риски, а
воспроизводимые дыры в контурах, которые концепты объявляют закрытыми. B3
обесценивает P13 для роли, ради которой P13 писался. B4 превращает
brute-force-защиту в самострел и обнуляет атрибуцию в audit trail.

**Рекомендация: пилот запускать после B1–B4** (оценка — один рабочий день с
тестами). S1–S8 честно фиксируются как долг пилота: S1/S2 — до первой миграции
коннектора на `HttpClient`; S3/S4 — до первого комплаенс-ревью audit trail;
S5 — до того, как диск закончится; S7 — сразу, красный сьют мешает работать.
