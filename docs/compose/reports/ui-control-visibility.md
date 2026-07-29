# Отчёт: UI — точки контроля, видимость логов и аудита

Спека: `docs/compose/specs/2026-07-29-ui-control-visibility-design.md`
План: `docs/compose/plans/2026-07-29-ui-control-visibility.md`

## Статус

Все 6 стадий (0–5) закодированы, покрыты тестами, зелёная сборка.
**Ручной чеклист на живом стенде с включённой auth не выполнен** — нужен
поднятый оркестратор с несколькими учётками разных ролей, вне
возможностей этой сессии. Список пунктов — в конце отчёта.

Изменения только в `ui/` и документации; `orchestrator/`, `soar/`,
`tests/`, `alembic/`, `deploy/` не тронуты — подтверждено `git status`.

## Что сделано

**Стадия 0 — фундамент.** `ui/src/permissions.js` — зеркало ролевых
кортежей бэкенда (`can(role, cap)`, 14 capability со ссылками на строки
роутеров); `ui/src/router-guard.js` закрывает прямой переход по URL, не
только пункт меню; единый toast вместо трёх способов показа ошибок;
`api.js` разделён на `request()`/`requestText()` — раньше `getLogs` был
сломан (`res.json()` на `PlainTextResponse`), лог не показывался вообще.
Добавлен `ui/src/session.js` — не-реактивный держатель роли для `api.js`
(избегает цикла импортов с `store/auth.js`).

**Стадия 1 — P2.** `ui/src/views/JobDetail.vue` (`/jobs/:id`): полный
traceback из `result_error`, результат, context (свёрнут), лог с
опросом раз в 2с, пока джоба не в терминальном статусе. `Jobs.vue` —
колонка Result, клик по строке, `dry_run`-бейдж.

**Стадия 2 — P8.** `ui/src/components/HistoryPanel.vue` — один компонент
на историю/diff/restore для workflow, action, connector(код) и
connector(конфиг), встроен вкладкой рядом с редактором в трёх вьюхах.
Capability на restore зависит от сущности (`connector.code.write` —
буквально `admin`, per BAGFIX B3; остальное — `admin`+`agent`).

**Стадия 3 — P9.** Разворачиваемая деталь строки в `Workflows.vue`:
docstring, schedule/interval/timeout/concurrency, ближайший запуск из
`GET /status`; для webhook — URL и токен под show/hide с copy-кнопками.

**Стадия 4 — P7/P4.** Роль `agent` в селекторах Users/ApiKeys переведена
на общий список `ROLES` (functionally уже была добавлена внешним
коммитом `1806c2a` до начала этой стадии — см. отклонения ниже).
`ui/src/views/Prompts.vue` — System (read-only, 404 → «не настроен») и
User (textarea, Save под `prompt.write`).

**Стадия 5.** `AuditLog.vue` — все 8 типов ресурсов (было 5, не хватало
`prompt`/`transfer`/`user`), фильтры `since`/`until` с тремя пресетами,
разворачиваемый detail, ссылка по `detail.commit`. Кнопка «Signature» в
Actions/Connectors через `/describe`.

## Тесты

58 тестов, 10 файлов, vitest + @vue/test-utils, `cd ui && npm test`.
Покрытие — чистые функции (`permissions`, `history-paths`, `webhook`,
`audit-filters`) плюс smoke-монтирование компонентов с моком `api`, как
и планировалось в [S9] спеки: вьюхи не покрыты построчно, только
ключевое поведение (кто что видит, traceback показывается, автообновление
останавливается на терминальном статусе и после unmount).

`npm run build` проходит на каждой стадии — ловит ошибки в шаблонах,
которые чистые unit-тесты не видят.

## Отклонения от плана

1. **`api.history` — вложенный неймспейс, не 12 плоских имён.**
   `api.history.workflow.getHistory(name)` вместо `api.getWorkflowHistory(name)`
   × 12. Та же покрываемость, меньше дублирования, проще мокается.

2. **Внешний коммит `1806c2a` опередил стадию 4.** Между стадиями 3 и 4
   в `main` появился коммит «fix(ui): show agent role option in
   Users/API keys dropdowns» — кто-то (судя по автору, параллельная
   сессия пользователя) захардкодил `<option value="agent">` в оба
   селектора в обход спек/план цикла. Не переделывалось и не
   откатывалось — вместо этого оба селектора доведены до `v-for` по
   `ROLES` из `permissions.js`, что и было целью пункта плана.

3. **`detail.commit` в аудите ведёт на список сущности, не на открытый
   коммит в `HistoryPanel`.** Довести до автооткрытия конкретной вкладки
   истории с предвыбранным коммитом — отдельная небольшая задача:
   `HistoryPanel` сейчас не принимает открывающий коммит через
   props/query, а живёт внутри state конкретной вьюхи-редактора.

4. **`setTimeout`-цепочка вместо `setInterval`** для автообновления
   джобы/лога — следующий тик планируется только после того, как
   предыдущий запрос вернулся, иначе при подвисшем `GET /jobs/{id}`
   запросы копятся.

Ни одно отклонение не сужает функциональный охват спеки — все пункты
[S10] Success Criteria закрыты кодом, кроме verification-пунктов,
требующих живого стенда.

## Побочная находка — M13

`GET /workflows` отдаёт webhook-токен (`token`) роли `viewer`
(`orchestrator/api/workflows.py:80,96-97`) — самой низкопривилегированной
read-only роли достаётся credential уровня «запустить произвольный
workflow». UI периметр не расширяет (значение и так читаемо через
DevTools авторизованным `viewer`), но сама раздача — баг бэкенда.
Заведено как **M13** в `docs/concepts/BAGFIX_PLAN.md`, не чинилось в
этом цикле (правка `orchestrator/`, вне скоупа "только UI").

## Ручной чеклист — не выполнен, нужен живой стенд

Стенд с включённой `auth.secret_key` и минимум 4 учётками
(viewer/analyst/admin/agent):

1. Упавший workflow → `/jobs/:id` показывает traceback целиком.
2. Запущенный workflow → лог дописывается сам, опрос прекращается на
   терминальном статусе (проверить в Network).
3. Сломать workflow → откатиться из `HistoryPanel` → workflow снова в
   реестре; в `/audit-log` есть `workflow.restore`.
4. Webhook-workflow → скопировать URL+токен из UI, `curl` → джоба
   создана, в аудите `job.create`.
5. `viewer` не видит кнопок Save/Delete/Run/Log, ни одного 403 в UI;
   `analyst` читает лог, не правит код.
6. Выдать ключ роли `agent` из UI → работает `PUT
   /workflows/{name}/code`, 403 на `/audit-log`.
7. `/audit-log` с `resource_type=transfer` и периодом за сутки
   показывает запись экспорта.

## Файлы

Новые: `ui/src/permissions.js`, `router-guard.js`, `session.js`,
`history-paths.js`, `webhook.js`, `audit-filters.js`,
`store/toast.js`, `components/Toast.vue`, `components/HistoryPanel.vue`,
`views/JobDetail.vue`, `views/Prompts.vue`, `tests/*.spec.js` (10 файлов),
`tests/setup.js`.

Изменены: `api.js`, `main.js`, `App.vue`, `store/auth.js`,
`views/{Jobs,Logs,Workflows,Actions,Connectors,Users,ApiKeys,AuditLog}.vue`,
`package.json`, `vite.config.js`, `CLAUDE.md`, `AGENTS.md`,
`docs/concepts/BAGFIX_PLAN.md` (M13).
