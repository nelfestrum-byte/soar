# Plan: UI — точки контроля, видимость логов и аудита

Спека: `docs/compose/specs/2026-07-29-ui-control-visibility-design.md`

Только `ui/`. Ни одной правки в `orchestrator/` и `soar/` — все данные
уже отдаются существующими роутами. Стадии 1–5 независимы друг от друга,
стадия 0 обязательна первой.

## Стадия 0 — фундамент: права, ошибки, тесты

### Tooling

- [x] Добавить в `ui/package.json`: `devDependencies` — `vitest`,
      `@vue/test-utils`, `jsdom`; скрипт `"test": "vitest run"`.
- [x] `ui/vite.config.js` — секция `test` (`environment: 'jsdom'`,
      `globals: true`).
- [x] Проверить, что `npm test` запускается на пустом наборе (0 тестов,
      exit 0), прежде чем писать первый тест.
- [x] **Сверх плана:** `ui/tests/setup.js` — in-memory `localStorage`.
      Окружение `jsdom` в vitest не отдаёт `localStorage` (сам jsdom его
      даёт, проверено отдельно), а Node 26 объявляет глобал и оставляет
      его `undefined` без `--localstorage-file`. Без шима падает любой
      тест, трогающий токены.

### Tests first

- [x] `ui/tests/permissions.spec.js` — для каждой из 5 ролей проверить всю
      таблицу capability. Обязательные кейсы: `viewer` не имеет
      `logs.read`; `agent` не имеет `connector.code.write`,
      `prompt.write`, `audit.read`, `auth.admin`; `agent` **имеет**
      `code.write` и `job.create`; `service` не имеет `job.cancel`.
      Падает — `permissions.js` ещё нет.
- [x] `ui/tests/api.spec.js` — с моком `fetch`:
      - `getLogs` возвращает строку из `res.text()`, не падает на
        `text/plain` (падает на текущем `api.js:65`);
      - 401 → один `POST /auth/refresh` → повтор исходного запроса с новым
        токеном;
      - повторный 401 → `clearTokens()` + вызов `onUnauthorized`;
      - 403 → в `Error.message` попадает роль пользователя.
- [x] **Сверх плана:** `ui/tests/nav.spec.js` — монтирование `App.vue` под
      разными ролями (состав меню) + `routeAllowed()` для всех
      capability-роутов. Без этого `can()` в шаблонах остался бы
      непроверенным.

### Implementation

- [x] `ui/src/permissions.js` — `ROLES` и `CAPS` по таблице [S3] спеки,
      с комментарием-ссылкой `orchestrator/api/*.py:<line>` на каждый
      кортеж; экспорт `can(role, cap)`. Добавлены не бывшие в спеке
      `connector.manage` (create/delete/generate — `connectors.py` `_ADMIN`),
      `connector.preview` и `workflow.toggle` (enable/disable — `_RW`).
- [x] **Сверх плана:** `ui/src/session.js` — не-реактивный держатель роли.
      `api.js` нужна роль для текста 403, но `store/auth.js` уже импортирует
      `api.js`; отдельный модуль убирает цикл импортов.
- [x] `ui/src/api.js` — `getLogs` через `res.text()` (общий `rawRequest()`
      + `request()`/`requestText()` поверх него); в обработчике ошибок
      добавлять роль к тексту 403.
- [x] `ui/src/store/toast.js` + `ui/src/components/Toast.vue`;
      смонтировать в `App.vue` рядом с `<main>`.
- [x] Заменить `alert()` на `notify.error()`: `Jobs.vue:69`,
      `Workflows.vue:190` и остальные вхождения (`grep -rn "alert(" ui/src`).
- [x] Применить `can()` в существующих вьюхах: `Jobs.vue` (Log, Cancel),
      `Workflows.vue` (Save, Delete, Run, Enable/Disable),
      `Actions.vue` (Save, Delete), `Connectors.vue` (Edit code, Setup,
      Create, Delete), `Settings.vue` (Export/Import — `transfer`).
      Правило: недоступное — скрыто; «Log» — `disabled` с `title`.
      `Settings.vue` изнутри не правился — весь экран закрыт роутовым
      guard'ом по `transfer`. Редакторы кода/конфига переведены в
      `readonly`, кнопка «Edit» для роли без записи называется «View».
- [x] `App.vue` — пункты меню по `can()`, а не по `auth.role === 'admin'`.
- [x] **Сверх плана:** `ui/src/router-guard.js` + `meta.cap` на роутах
      `/generate`, `/settings`, `/users`, `/api-keys`, `/audit-log`.
      Спрятанный пункт меню не закрывает прямой переход по URL — экран
      открывался и сыпал 403 на каждом запросе.

### Verification

- [x] `npm test` зелёный — 25 тестов в 3 файлах.
- [x] `npm run build` проходит (проверка шаблонов, которые тестами не
      покрыты).
- [x] Правок в `orchestrator/`/`soar/` нет — `git status` показывает
      только `ui/` и `docs/`.
- [ ] Вручную: `viewer` не видит ни одной кнопки, ведущей к 403 —
      **не выполнено**, нужен поднятый стенд с четырьмя учётками разных
      ролей. Переносится в финальный ручной чеклист.

## Стадия 1 — экран джобы: результат, traceback, живой лог (P2)

### Tests first

- [x] `ui/tests/job-detail.spec.js` — smoke-монтирование `JobDetail.vue`
      с моком `api.getJob`/`api.getLogs`: для `failed`-джобы traceback из
      `result_error` присутствует в разметке и развёрнут; для
      `completed` — блок ошибки отсутствует. Плюс: context свёрнут по
      умолчанию (не «развёрнут», как было в исходной формулировке пункта —
      уточнено по [S4] спеки при написании теста); лог не запрашивается
      для роли без `logs.read` (viewer).
- [x] Тест таймера: при `status: 'running'` после
      `vi.advanceTimersByTimeAsync` происходит повторный запрос; при
      `status: 'failed'` — не происходит; после `unmount()` опрос не
      возобновляется.

### Implementation

- [x] `ui/src/views/JobDetail.vue` — секции из [S4]: шапка, результат
      (`result_success`/`result_data`/`result_error`), context (свёрнут),
      лог, deep-link в аудит.
- [x] Автообновление: `setTimeout`-цепочка (не `setInterval` — следующий
      тик планируется только после того, как предыдущий запрос вернулся,
      иначе при подвисшем `GET /jobs/{id}` запросы накапливаются) 2 с,
      только пока статус `pending`/`running`; очистка в `onUnmounted`.
- [x] Роут `{ path: '/jobs/:id', component: JobDetail }` в
      `ui/src/main.js`.
- [x] `Jobs.vue` — колонка Result (`✓`/`✗` + обрезанная первая строка
      ошибки), строка кликабельна на `/jobs/:id` (кнопки действий —
      `@click.stop`, чтобы не триггерить переход), признак `dry_run` из
      `job.context`, фильтры принимают `workflow_name`/`status` из query
      при монтировании (для ссылки со стадии 3).
- [x] `Logs.vue` — то же автообновление: догружает статус джобы через
      `getJob` после каждого чтения лога и продолжает опрос, пока он не
      терминальный; работает через исправленный `getLogs`.

### Verification

- [x] `npm test` зелёный — 33 теста в 4 файлах.
- [x] `npm run build` проходит.
- [ ] Вручную: запустить заведомо падающий workflow → traceback виден на
      `/jobs/:id`; запустить долгий → лог дописывается, опрос
      прекращается после завершения (проверить в Network) — переносится в
      финальный ручной чеклист (нужен поднятый стенд).

## Стадия 2 — история, diff, откат (P8)

### Tests first

- [x] `ui/tests/history-paths.spec.js` — таблица путей (реализована как
      `ui/src/history-paths.js::HISTORY_PATHS`, а не приватная `PATHS`
      внутри компонента — общий модуль нужен и `api.js`, и `HistoryPanel`)
      даёт корректные URL для `workflow`, `action`, `connector_code`,
      `connector_config` (сверено с
      `orchestrator/api/{workflows,actions,connectors}.py`; у action нет
      сегмента `/code` — единственная асимметрия в таблице).
- [x] `ui/tests/history-panel.spec.js` — 6 тестов: список коммитов в
      порядке, отданном бэкендом; просмотр версии по клику; diff после
      выбора обоих радио A/B; «Restore» скрыт для роли без capability
      (кейс из плана — `agent` на `connector_code`, capability
      `connector.code.write` даёт только `admin`, см. B3); «Restore»
      вызывает API только после подтверждения `confirm()`.

### Implementation

- [x] `ui/src/api.js` — `api.history.{workflow,action,connectorCode,
      connectorConfig}.{getHistory,getVersion,getDiff,restore}` (12
      комбинаций через общий `historyApi(entity)` над
      `HISTORY_PATHS`) — не 12 отдельных плоских имён, как было
      сформулировано в исходном пункте плана: вложенный неймспейс даёт ту
      же покрываемость с меньшим дублированием и проще мокается в тестах.
- [x] `ui/src/components/HistoryPanel.vue` — список коммитов, просмотр
      версии, выбор A/B + diff с подсветкой по первому символу строки,
      «Restore» с `confirm()` под `can()`. Capability на restore зависит
      от `entity`: `restore` для workflow/action,
      `connector.code.write`/`connector.config.write` для коннектора —
      единая capability `'restore'` из спеки не покрывала бы B3
      (агенту нельзя писать код коннектора, но можно откатывать
      workflow), поэтому в компоненте — таблица `RESTORE_CAP` по entity.
- [x] Встроено вкладками (Code/History, Config/History) в
      `Workflows.vue`, `Actions.vue`, `Connectors.vue` (для коннектора —
      раздельные вкладки на код и на конфиг, каждая со своей историей).
- [x] После успешного restore — `HistoryPanel` эмитит `restored`,
      вьюха вызывает тот же `editWorkflow`/`loadAction`/`editCode`/
      `editConfig`, что и при открытии редактора (перезагружает и
      содержимое, и список коммитов за один вызов), плюс toast.

### Verification

- [x] `npm test` зелёный — 43 теста в 6 файлах.
- [x] `npm run build` проходит.
- [ ] Вручную: сломать workflow → откатиться из UI → workflow снова в
      реестре; в `/audit-log` появилась запись `workflow.restore` —
      переносится в финальный ручной чеклист.
- [ ] Вручную: diff версий конфига коннектора, где менялось соседнее с
      секретом поле → значения hidden-полей замаскированы (регрессия B2 со
      стороны UI) — переносится в финальный ручной чеклист.

## Стадия 3 — webhook и расписание (P9)

### Tests first

- [x] `ui/tests/webhook-url.spec.js` — сборка
      `${origin}/api/webhooks/${name}` и `curl`-примера с заголовком
      `X-Webhook-Token`. Подтверждено по `deploy/prod/nginx.conf:13-19` и
      `ui/vite.config.js` (dev proxy) — `/api/` проксируется на бэкенд без
      дополнительного переписывания пути, так что этот URL реальный
      внешний адрес вебхука, не только внутренняя договорённость UI.

### Implementation

- [x] `ui/src/webhook.js` — чистые функции `webhookUrl`/`webhookCurl`,
      вынесены из компонента, чтобы быть тестируемыми без монтирования.
- [x] `Workflows.vue` — разворачиваемая деталь строки (клик по стрелке
      или по имени файла, состояние — `Set` открытых имён): `docstring`,
      `schedule`/`interval`, `timeout`, `concurrency`.
- [x] Для `type === 'webhook'`: URL + токен под «показать/скрыть», кнопки
      «Copy URL» / «Copy curl» (`navigator.clipboard`, тихий toast-фолбэк
      при недоступном clipboard — headless/http-контекст).
- [x] Ближайший запуск для `scheduled` — сопоставлением с
      `status.scheduler.next_runs` (`GET /status`, ключ — `wf.name`,
      т.е. имя файла: `scheduler.py:35` строит `job.id` из `meta.name`,
      это то же значение, что и ключ workflow во всём проекте согласно
      `CLAUDE.md` — «Workflow key: имя файла без `.py`»).
- [x] Ссылка «Jobs этого workflow» → `/jobs?workflow_name=<name>` (в
      каждой строке, не только в детали) — `Jobs.vue` уже читает
      `workflow_name` из query с стадии 1.

### Verification

- [x] `npm test` зелёный — 46 тестов в 7 файлах.
- [x] `npm run build` проходит, включая шаблон `Workflows.vue` с новой
      разметкой (сборка компилирует шаблоны — ловит опечатки в
      директивах, которые unit-тесты на чистых функциях не поймают).
- [ ] Вручную: скопировать URL и токен из UI, дёрнуть `curl` → джоба
      создана, в аудите `job.create` — переносится в финальный ручной
      чеклист.

## Стадия 4 — роль `agent` и промпты (P7, P4)

### Tests first

- [x] `ui/tests/prompts.spec.js` — 5 тестов: `content: null` от
      `GET /prompts/user` даёт пустое поле, не строку `"null"`; 404 от
      `/prompts/system` показывается как «не настроен», не как ошибка
      (и не как `.error`-баннер); кнопка «Save» и запись в textarea
      отсутствуют для роли без `prompt.write`; сохранение показывает
      commit-хеш.
- [x] `ui/tests/roles-select.spec.js` — селекторы ролей в `Users.vue` и
      `ApiKeys.vue` содержат все `ROLES`, включая `agent`.

### Implementation

- [x] **Внешнее изменение, обнаруженное при подготовке этой стадии:**
      между стадией 3 и стадией 4 в `main` уже прилетел коммит `1806c2a`
      («fix(ui): show agent role option in Users/API keys dropdowns») —
      кто-то параллельно захардкодил `<option value="agent">` в оба
      селекта в обход спека/план цикла. Функционально это закрывало
      P7 частично; не переделывался — вместо этого оба селекта
      переведены на `v-for="r in ROLES"` из `permissions.js` (уже
      использовался остальным UI как единый источник правды), что и
      было целью пункта плана. Никакого отката чужого коммита не
      делалось.
- [x] `ui/src/views/Prompts.vue` — System (read-only, 404 → «не
      настроен») и User (textarea, `readonly` без `prompt.write`, Save
      под `can(role,'prompt.write')`, commit-хеш в результате).
- [x] Роут `/prompts` + пункт меню в `App.vue`. Без `meta.cap` — читает
      `GET /prompts/system|user` на `_RO`, доступен всем ролям, как и
      сам роут на бэкенде.

### Verification

- [x] `npm test` зелёный — 53 теста в 9 файлах.
- [x] `npm run build` проходит.
- [ ] Вручную: выдать ключ роли `agent` из UI → работает `PUT
      /workflows/{name}/code`, 403 на `/audit-log` — переносится в
      финальный ручной чеклист.
- [ ] Вручную: сохранить пользовательский промпт → в `/audit-log` есть
      `prompt.update_user` с коммитом — переносится в финальный ручной
      чеклист.

## Стадия 5 — аудит и интроспекция

### Tests first

- [x] `ui/tests/audit-filters.spec.js` — 5 тестов на
      `ui/src/audit-filters.js` (вынесено в отдельный модуль, как
      `webhook.js` на стадии 3, чтобы не мокать `Date.now()` внутри
      монтированного компонента): `RESOURCE_TYPES` содержит все 8 типов
      (сверено `grep -rhoE 'resource_type="[a-z_]+"' orchestrator/`);
      `presetRange('hour'|'day'|'week', now)` считает границы; неизвестный
      пресет даёт `{since: null, until: null}`, а не бросает исключение.

### Implementation

- [x] `AuditLog.vue` — `resourceTypes` теперь `RESOURCE_TYPES` из
      `audit-filters.js` (все 8: `workflow, action, connector, apikey,
      job, prompt, transfer, user`) вместо захардкоженных 5.
- [x] Фильтры `since`/`until` (`<input type="datetime-local">`) + три
      кнопки-пресета (час/сутки/неделя), которые заполняют оба поля и
      сразу перезагружают список.
- [x] `detail` — по клику разворачивается в `<pre>` с
      `JSON.stringify(..., null, 2)` вместо постоянно видимой одной
      строки; при наличии `detail.commit` — `router-link` на список
      соответствующей сущности (`workflow`→`/workflows`,
      `action`→`/actions`, `connector`→`/connectors`) с обрезанным до 8
      символов хешем в тексте ссылки.
      **Отклонение от формулировки пункта:** ссылка ведёт на список
      сущности, не на уже открытую и подсвеченную запись в
      `HistoryPanel` конкретного коммита — `HistoryPanel` встроен в
      состояние редактора конкретной вьюхи и не принимает открывающий
      коммит через query/props в этом цикле; довести до автооткрытия
      вкладки History с нужным коммитом предпросмотренным — отдельная
      небольшая задача, не блокирующая суть находки (коммит из аудита
      находим вручную в уже открывшемся списке истории).
- [x] `api.js` — `getActionDescribe`, `getConnectorDescribe`.
- [x] Кнопка «Signature» — третья вкладка (Code/Signature/History) в
      `Actions.vue` и `Connectors.vue` (только для кода коннектора, не
      для конфига — `describe` есть только у `/connectors/{name}/describe`,
      не у `/config`), разметка таблицы методов переиспользована из
      `Tools.vue:32-39`.

### Verification

- [x] `npm test` зелёный — 58 тестов в 10 файлах.
- [x] `npm run build` проходит.
- [ ] Вручную: `/audit-log` с `resource_type=transfer` и периодом за
      сутки показывает запись экспорта; клик по `detail.commit` ведёт на
      список сущности (не на конкретный коммит — см. отклонение выше) —
      переносится в финальный ручной чеклист.

## Финализация

- [ ] Полный ручной чеклист из [S9] спеки на стенде с **включённой** auth
      (`auth.secret_key` задан) — 7 пунктов. **Не выполнено** — нужен
      поднятый оркестратор с несколькими учётками разных ролей, вне
      возможностей этой сессии; список пунктов зафиксирован в отчёте.
- [x] `python -m pytest tests/ -q` — 756 passed, 1 skipped. Совпадает с
      известным базовым состоянием после закрытия S7 в BAGFIX_PLAN (тест-сьют
      зелёный); правок бэкенда в этом цикле не было.
- [x] Завести **M13** в `docs/concepts/BAGFIX_PLAN.md`: `GET /workflows`
      отдаёт webhook-токен роли `viewer` (`workflows.py:80,96-97` на
      `_RO`) — credential уровня «запустить произвольный workflow» у
      самой низкопривилегированной роли. Правка бэкенда, не в этот цикл.
- [x] Обновить `CLAUDE.md` (`ui/` больше не «не читать» — стенд,
      дорабатываемый до продакшена) и `AGENTS.md` — после выполнения
      кодовой части.
- [x] Написать `docs/compose/reports/ui-control-visibility.md`.
