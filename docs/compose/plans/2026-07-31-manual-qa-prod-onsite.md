# Промпт для отдельной сессии: ручное E2E QA на чистом prod-стенде (on-site, роль admin)

> Это не спек и не implementation-план в обычном смысле CLAUDE.md — это
> готовый промпт-сценарий для **новой** Claude Code сессии, которая проведёт
> ручное QA. Скопируй содержимое ниже (или укажи путь к этому файлу) в новую
> сессию как первое сообщение.

---

## ПРОМПТ (для новой сессии — всё, что ниже этой черты, адресовано тебе)

Ты проводишь ручное end-to-end тестирование SOAR на чистом prod-стенде,
поднятом на этой же машине. Цель — не «прогнать тесты», а пройти сценарий
реального применения продукта: развернуть стенд → создать коннектор,
использующий tools платформы → создать на его основе экшены → собрать из них
рабочий поток → запустить → проверить через API, что результат, логи и аудит
соответствуют документированному поведению. Роль во всех действиях — `admin`.

### Перед стартом — прочитать

- `AGENTS.md` (весь, это индекс проекта) — особенно разделы «Модель
  сущностей», «Key patterns» (Connector Proxy, dry-run, audit trail), «API
  Endpoints», «Runner contract»
- `CLAUDE.md` — рабочие правила репозитория
- `docs/concepts/ENTITY-MODEL.md` — часть 1 (принципы 1–5) обязательна;
  часть 2 (дрейф E1–E10) — бегло, чтобы узнавать симптомы, если наткнёшься
- `docs/agents/api-reference.md` — таблицы эндпоинтов
- `docs/agents/known-limitations.md` и `docs/agents/security-patterns.md` —
  чтобы не путать документированное поведение с дефектом

Не читай остальной код заранее «на всякий случай» — то, что понадобится по
ходу (например, точный формат `SOAR_AUDIT_EVENT`), уже приведено ниже с
указанием файла-источника, где я это проверил.

### Жёсткие правила выполнения

1. **Без скриптов автоматизации.** Каждый шаг — один осмысленный вызов
   (curl/httpie/docker), выполненный руками. Посмотрел на ответ → оценил,
   ожидаемо это или нет → записал в лог → пошёл дальше. Не пиши bash-цикл,
   который прогоняет все эндпоинты подряд без анализа между вызовами.
2. **Каждое действие и результат — строка в QA-логе** (формат и путь ниже).
   Пишешь лог по ходу, не восстанавливаешь из памяти в конце.
3. **Роль admin** на всех мутирующих вызовах. Отдельные RBAC-проверки под
   другой ролью (Phase 9) — осознанное исключение, не default.
4. **Не чини молча.** Если что-то не работает как задокументировано —
   зафиксируй как дефект в логе, попробуй понять причину через логи/аудит/
   повторный запрос с другими параметрами, но не переписывай код продукта
   по ходу QA, чтобы обойти проблему. Точечная правка своего же QA-контента
   (коннектор/экшен/воркфлоу, которые ты сам создал на Phase 3–5) — это
   нормальная часть цикла «написал → запустил → увидел ошибку → поправил»,
   не automation.
5. **Docker чистится только в рамках этого проекта.** `docker compose down
   -v` для stage/prod compose-файлов этого репозитория и точечное удаление
   контейнеров/volume с именами `soar-*`, если что-то осталось. Не
   `docker system prune -a` и не трогать образы/контейнеры, не относящиеся
   к soar — на машине есть другие проекты.
6. **Секреты не в лог.** Пароль admin/API-ключи — используй, но не записывай
   plaintext в лог-файл, который попадёт в git-историю репозитория. Фиксируй
   факт («admin создан, пароль сохранён в shell-сессии»), не значение.

### Куда писать

- Лог (создать в начале, дописывать по ходу):
  `docs/compose/reports/manual-qa-prod-onsite.log.md`
- Отчёт (создать в конце, на основе лога):
  `docs/compose/reports/manual-qa-prod-onsite.md`

Формат строки лога:
```
[HH:MM:SS] <Phase>.<Step> — METHOD /path — actor=admin — status=NNN — verdict=OK|FAIL|SUSPICIOUS
  request: <кратко, без секретов>
  response: <кратко, ключевые поля>
  note: <только если FAIL/SUSPICIOUS — что не так и почему, со ссылкой на то, где в доках описано ожидаемое поведение>
```

---

## Phase 0 — Чистый стенд: prod on-site (checkout = инстанс)

Выбранный режим деплоя (см. `docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md`,
реализовано с v0.16): рабочая директория `d:\projects\soar` сама становится
инстансом через `deploy/prod/`, без отдельного bundle/air-gap шага — эта
машина имеет интернет для сборки образов на месте.

0.1. `git status` — убедиться в состоянии репозитория (на момент написания
     этого промпта: чисто, ветка `main`). Если есть незакоммиченные
     изменения — не твои, не трогай, работай поверх.

0.2. Убедиться, что рядом лежит sibling-репозиторий контентпака (нужен для
     сборки образа, `COPY --from=basepack` в `Dockerfile.orchestrator`):
     ```bash
     ls ../soar-content-pack
     ```
     На момент написания этого промпта репозиторий на месте
     (`d:/projects/soar-content-pack`). Если его нет — это блокер Phase 0,
     сборка упадёт на `docker build`; остановись и сообщи, а не пытайся
     работать без него.

0.3. Очистить старое состояние (только soar):
     ```bash
     docker compose -f deploy/stage/docker-compose.yml down -v 2>/dev/null
     docker compose -f deploy/prod/docker-compose.yml down -v 2>/dev/null
     docker ps -a --filter "name=soar-"
     docker volume ls --filter "name=soar-"
     ```
     Если что-то осталось после `down -v` — убрать точечно по имени.
     На момент написания этого промпта `docker ps` пуст (проверено).

0.4. Preflight:
     ```bash
     python deploy/soarctl doctor
     ```
     На этом шаге `.env` ещё не существует — пункт `env` в выводе будет
     FAIL, это ожидаемо (см. `deploy/soarctl_lib/doctor.py`). Остальные
     пункты (`docker`, `docker compose`, `ports`, `disk space`) должны быть
     OK. Если порты 8000/3000 заняты — разберись, чем (другой проект?), не
     убивай процесс не глядя.

0.5. Собрать образы и подготовить инстанс:
     ```bash
     python deploy/soarctl install
     ```
     Это: `git describe` для версии, `docker build` для orchestrator (два
     venv — platform+content, плюс `COPY --from=basepack`) и ui, запись
     `deploy/prod/VERSION` + `deploy/prod/source.json`. Сборка займёт
     несколько минут. **Внимательно следи за выводом** — сборка prod-образа
     с реальным `--build-context basepack=...` для `deploy/prod` ранее не
     была явно верифицирована живым запуском (в отличие от `deploy/stage`,
     где это уже проверяли, см. `docs/compose/reports/content-as-contentpack.md`
     addendum) — если тут что-то падает, это находка, а не твоя ошибка.

0.6. Инициализировать секреты/конфиг:
     ```bash
     python deploy/soarctl init --cors-origin http://localhost:3000
     ```
     Не используй `--interactive` — рассчитан на реальный TTY-prompt
     (`input()`), в среде агента это может зависнуть.
     Прочитать `deploy/prod/.env` и `deploy/prod/config.yaml` после
     генерации: убедиться, что `AUTH_SECRET_KEY`/`auth.secret_key` не
     пустые (нужен настоящий JWT-flow, не анонимный admin — см.
     `auth.secret_key = ""` в AGENTS.md), `server.trusted_proxies` содержит
     `172.28.0.10`.

0.7. Поднять стек:
     ```bash
     python deploy/soarctl up
     python deploy/soarctl status
     docker compose -f deploy/prod/docker-compose.yml --env-file deploy/prod/.env ps
     ```
     Все 4 сервиса (redis/postgres/orchestrator/ui) — `healthy`.

0.8. Миграции (первый деплой на чистую БД → `stamp`, не `upgrade` — см.
     AGENTS.md, landmine про Alembic):
     ```bash
     python deploy/soarctl migrate --fresh
     ```

0.9. Завести admin-пользователя. `soarctl users create` не даёт передать
     `--password` флагом и рассчитывает на интерактивный `getpass` внутри
     `docker compose exec` — в среде без TTY это зависнет. Обойди пайпом
     напрямую (тот же вызов, что под капотом у `soarctl users create`, см.
     `deploy/soarctl_lib/users.py`):
     ```bash
     echo "<придумай пароль>" | docker compose -f deploy/prod/docker-compose.yml \
       --env-file deploy/prod/.env exec -T orchestrator \
       python -m orchestrator.auth.cli create-user --username admin --role admin
     ```

0.10. Проверить доступность:
      ```bash
      curl -s http://localhost:8000/health
      curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/
      ```

Это закрывает ограничение 1 (чистый прод-стенд на этой машине).

---

## Phase 1 — Аутентификация как admin

1.1. `POST /auth/login` `{"username": "admin", "password": "..."}` →
     сохрани `access_token`/`refresh_token` в переменные шелла (не в лог).
1.2. `GET /auth/me` с `Authorization: Bearer $TOKEN` → `role: admin`.
1.3. `POST /auth/keys` — создать service-ключ, убедиться что секрет
     возвращается один раз; `GET /auth/keys` — убедиться что повторно
     секрет не отдаётся.

---

## Phase 2 — Discovery (принцип 4 ENTITY-MODEL: «проект объясняет себя через API»)

Смысл фазы: убедиться, что всё нужное для написания коннектора/экшена/
воркфлоу реально достаётся из API, без чтения исходников и без `docker exec`.

- `GET /tools` — найти `http_client` в списке (синглтон, `module: "__init__"`)
- `GET /tools/http_client` (или как он реально называется в ответе выше) —
  докстринг + сигнатуры методов. Запиши точные сигнатуры `get_json`/
  `post_json` — они понадобятся в Phase 3 буквально, не по памяти.
- `GET /runtime` — проверь, что `httpx` есть в `guaranteed`
- `GET /connectors/template`, `GET /actions/template`, `GET /workflows/code/template`
- `GET /connectors` — должны быть видны 24 встроенных коннектора из
  content-pack, если сидинг на старте отработал (`seed_connector_pack`,
  Content-as-Contentpack Phase 3) — если список пуст, это находка для
  отчёта, не блокер для Phase 3 (создаёшь новый коннектор независимо)
- `GET /prompts/system` — просто факт-чек, не критично

---

## Phase 3 — Создать коннектор, использующий tools платформы

Пиши **новый** коннектор (не трогай контентпак), который использует
`soar.tools.http_client_sync` — то есть контент, обращающийся к
инструменту платформы, полностью через API.

3.1. `POST /connectors/qa_httpbin?class_name=QaHttpbinConnector` — создать
     заготовку из шаблона.
3.2. `PUT /connectors/qa_httpbin/code` — реализация (сверь имена методов
     `get_json`/`post_json` с тем, что реально вернул `GET /tools/http_client`
     на Phase 2 — если сигнатура отличается от приведённой ниже, адаптируй
     под факт, не держись за этот пример):
     ```python
     from typing import ClassVar

     from soar.connectors.base import BaseConnector
     from soar.tools import http_client_sync


     class QaHttpbinConnector(BaseConnector):
         """QA-коннектор: обёртка над httpbin.org для проверки прозрачного
         логирования/аудита через ConnectorProxy."""

         HIDDEN_FIELDS: ClassVar[set[str]] = {"api_key"}
         MUTATING_METHODS: ClassVar[set[str]] = {"send_event"}

         def __init__(self, instance_name: str, base_url: str = "https://httpbin.org", api_key: str = "", **kwargs):
             super().__init__(instance_name)
             self.base_url = base_url
             self.api_key = api_key

         def _connect_impl(self) -> None:
             self._connected = True

         def get_ip(self) -> dict:
             self._ensure_connected()
             return http_client_sync.get_json(f"{self.base_url}/ip")

         def send_event(self, payload: dict) -> dict:
             self._ensure_connected()
             return http_client_sync.post_json(f"{self.base_url}/post", payload)
     ```
     Если `httpbin.org` недоступен из контейнера (сеть/прокси на этой
     машине) — замени на любой другой публичный echo-эндпоинт
     (`https://api.ipify.org?format=json` и т.п.) и зафиксируй в логе,
     почему сменил.
3.3. `PUT /connectors/qa_httpbin/config`:
     ```yaml
     instances:
       qa_httpbin:
         base_url: "https://httpbin.org"
         api_key: "qa-test-secret"
     ```
3.4. `GET /connectors/qa_httpbin/schema` — `api_key` должен быть `hidden: true`.
3.5. `GET /connectors/qa_httpbin/config` — значение `api_key` замаскировано
     `********`, даже для admin (см. api-reference.md).
3.6. `GET /connectors/qa_httpbin/describe` — сверить сигнатуры `get_ip`/`send_event`.
3.7. `GET /connectors/qa_httpbin/code/history` — коммит создан автоматически,
     автор — реальный admin-пользователь (`git_author(user)`), не дефолт из
     `git.author_name` в конфиге.

---

## Phase 4 — Создать экшены поверх коннектора

Экшены — простая интеграционная логика, без внутренней механики платформы.

4.1. `PUT /actions/check_qa_ip`:
     ```python
     from soar.connectors.qa_httpbin import qa_httpbin


     def check_qa_ip() -> dict:
         """Возвращает внешний IP через QA-коннектор httpbin (read-only)."""
         return qa_httpbin.get_ip()
     ```
4.2. `PUT /actions/notify_qa_event`:
     ```python
     from soar.connectors.qa_httpbin import qa_httpbin


     def notify_qa_event(message: str) -> dict:
         """Отправляет тестовое событие через QA-коннектор (мутирующий вызов, для проверки dry-run)."""
         return qa_httpbin.send_event({"message": message})
     ```
4.3. `GET /actions` — оба в списке, `summary` = первая строка докстринга.
4.4. `GET /actions/check_qa_ip/describe`, `GET /actions/notify_qa_event/describe`
     — сверить сигнатуры.

---

## Phase 5 — Собрать рабочий поток

5.1. `PUT /workflows/qa_manual_test/code`:
     ```python
     from soar.actions.check_qa_ip import check_qa_ip
     from soar.actions.notify_qa_event import notify_qa_event
     from soar.workflows.base import ManualWorkflow


     class QaManualTestWorkflow(ManualWorkflow):
         """QA E2E: дёргает httpbin через коннектор+экшены, проверка логов/аудита."""

         def run(self, context: dict) -> dict:
             ip_info = check_qa_ip()
             notify_result = notify_qa_event(f"qa-run {context.get('label', 'manual')}")
             return {"ip_info": ip_info, "notify_result": notify_result}
     ```
5.2. `POST /workflows/qa_manual_test/enable`
5.3. `GET /workflows/qa_manual_test` — `docstring` заполнен, `enabled: true`,
     `workflow_type: manual`.
5.4. `GET /workflows` — воркфлоу в списке.

---

## Phase 6 — Запустить

6.1. **Dry-run сначала.** `POST /jobs`:
     ```json
     {"workflow_name": "qa_manual_test", "context": {"dry_run": true, "label": "dryrun"}}
     ```
     `context["dry_run"]` — задокументированная конвенция (AGENTS.md,
     `soar/runner.py`). Ожидание, по коду `soar/connectors/_proxy.py`:
     `send_event` — в `MUTATING_METHODS`, под `dry_run=true` вызов
     блокируется на границе прокси и возвращает `None`, **не** делает
     реальный HTTP-запрос. `get_ip` — не мутирующий, выполняется как обычно.
     Значит ожидаемый результат джобы: `data.ip_info` — реальный ответ,
     `data.notify_result` — `null`.
     Дождись завершения (`GET /jobs/{id}` до status `COMPLETED`/`FAILED`).
     Если фактический результат разошёлся с этим ожиданием — это находка,
     запиши в лог как SUSPICIOUS/FAIL с конкретикой.

6.2. **Реальный запуск.** `POST /jobs`:
     ```json
     {"workflow_name": "qa_manual_test", "context": {"label": "real"}}
     ```
     Оба вызова должны дать реальные ответы httpbin.

6.3. Если джоба `FAILED` — не чини вслепую: `GET /jobs/{id}` (error/
     traceback), `GET /logs/{id}` (полный лог). Пойми причину, зафиксируй,
     при необходимости точечно поправь свой же код (Phase 3–5) через тот же
     API и повтори — это нормальный QA-цикл, не автоматизация.

---

## Phase 7 — Логи

Для job_id из 6.1 и 6.2:

7.1. `GET /logs/{job_id}` — найди строки:
     - `SOAR_AUDIT_EVENT connector.call target=qa_httpbin.qa_httpbin.get_ip ... outcome=ok ...`
     - для dry-run джобы: `SOAR_AUDIT_EVENT connector.call.dry_run target=qa_httpbin.qa_httpbin.send_event ...`
       (не `connector.call` — это отдельный тип события у заблокированного
       вызова, см. `soar/connectors/_proxy.py`)
     - для реальной джобы: `SOAR_AUDIT_EVENT connector.call target=...send_event ... outcome=ok ...`
     Сверь фактический формат с этими двумя паттернами дословно — если
     реальная строка отличается (другие поля/порядок), это не обязательно
     баг, но зафиксируй расхождение с тем, что описано в AGENTS.md.

7.2. **Дополнительная проверка редакции (необязательно, но информативно):**
     редакция `HIDDEN_FIELDS` в прокси применяется только к **именованным
     kwargs** вызова метода (`safe_kwargs`), не к позиционным `args` — см.
     `soar/connectors/_proxy.py::_wrapped`. В текущей реализации `send_event`
     ты вызываешь позиционно (`send_event({"message": ...})`), так что
     `api_key` там вообще не участвует — это ожидаемо, `api_key` живёт в
     конфиге коннектора, не передаётся вызовом. Если хочешь предметно
     проверить именно kwargs-редакцию прокси — добавь метод, принимающий
     именованный аргумент с именем, совпадающим с полем из
     `HIDDEN_FIELDS`, вызови его с этим kwarg и убедись, что в логе он
     заменён на `***`. Отдельный пункт, не блокирует остальной сценарий.

7.3. `GET /logs/{job_id}/stream` (SSE) — на новом запуске джобы (можно
     Phase 6.2 повторить с `label: "stream-check"`) — убедиться, что стрим
     реально идёт по мере выполнения, не только отдаёт финальный дамп разом.

---

## Phase 8 — Аудит

8.1. `GET /audit-log?resource_type=connector&resource_id=qa_httpbin` —
     записи о create/`code` PUT/`config` PUT, `actor` = admin.
8.2. `GET /audit-log?resource_type=action` — записи по обоим экшенам.
8.3. `GET /audit-log?resource_type=workflow&resource_id=qa_manual_test` —
     create (PUT code) + enable.
8.4. `GET /audit-log?resource_type=job` — `job.create` для обоих запусков
     (6.1 и 6.2), `detail.workflow_name = qa_manual_test`.
     Про actor для JWT — известное ограничение (`known-limitations.md` #6):
     `actor_name` может быть числовым id, не логином. Не путай это с
     дефектом, если увидишь id вместо `"admin"`.
8.5. Сверь, что restore-эндпоинты (если тестируешь их в Phase 9) не пишут
     unexpected дубли аудита — по одной записи на реальную мутацию.

---

## Phase 9 — Дополнительное покрытие (по возможности, не блокирует итог)

Выполняй по остаточному времени, в любом порядке:

- **History/diff/restore workflow:** вторая правка `PUT /workflows/qa_manual_test/code`
  → `GET .../code/history` → `GET .../code/diff?a=&b=` → `POST .../code/restore`
  — проверь, что restore реально триггерит reload (AGENTS.md: restore
  workflow-кода триггерит reload, restore action/connector — нет, это не
  баг, а документированная асимметрия).
- **Webhook:** создай второй воркфлоу `WebhookWorkflow`-типа поверх того же
  коннектора, `POST /webhooks/{name}` с заголовком `X-Webhook-Token`,
  сверить с `token`, заданным на самом классе воркфлоу (поле per-workflow,
  не общий секрет — `SOAR_WEBHOOK_TOKEN` из `deploy/prod/.env` тут ни при
  чём, это не токен, который проверяют webhook-воркфлоу). Проверь и
  негативный кейс — неверный токен → 403, залогирован warning
  (security-event logging, AGENTS.md).
- **Status:** `GET /status` после нескольких job — сверь counts с реально
  запущенными джобами.
- **Transfer:** `POST /transfer/export` → `POST /transfer/import` (сначала
  без `force`, ожидай conflict-preflight без аудита; потом с `force`,
  ожидай запись `transfer.import` в аудите).
- **RBAC:** `POST /auth/users` создать `analyst`-пользователя, залогиниться
  под ним, попробовать `PUT /connectors/qa_httpbin/config` с реальным
  (не `********`) значением `api_key` — должен быть `403` (реальное
  изменение hidden-поля требует буквально `admin`, не любой RW — см.
  api-reference.md).
- **Rate limiting:** не нужно всерьёз нагружать стенд — если любопытно,
  несколько быстрых неверных `/auth/login` подряд должны словить `429`
  раньше, чем обычный лимит (5/60s на login, см. AGENTS.md).

---

## Phase 10 — Завершение

10.1. Перечитай лог целиком.
10.2. Напиши отчёт `docs/compose/reports/manual-qa-prod-onsite.md` со
      структурой:
      1. Итог одной строкой (стенд поднят, сценарий пройден целиком/
         частично, N дефектов найдено, критичность)
      2. Таблица покрытых эндпоинтов по фазам (метод/путь/verdict)
      3. Найденные дефекты — по одному пункту: что сделано → что
         ожидалось (со ссылкой на AGENTS.md/api-reference.md/ENTITY-MODEL.md)
         → что получилось фактически → воспроизводимо ли → предварительная
         классификация (баг в API / дрейф от модели сущностей, если похоже
         на E1–E10 паттерн / неточность в документации)
      4. Что не покрыто в этом проходе
      5. Как остановить стенд (`python deploy/soarctl down`) и как поднять
         заново (весь Phase 0 от `install`, если образы нужно пересобрать,
         или только `up` + `migrate`, если только контейнеры остановлены)
10.3. **Не сноси стенд сам.** Оставь поднятым — отчёт может понадобиться
      смотреть руками поверх живого API. Просто зафиксируй команду
      остановки в отчёте.
