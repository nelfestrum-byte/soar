# UI: точки контроля, видимость логов и аудита

> Ревизия `ui/` относительно всего, что реализовано по `docs/concepts/`
> (`UPGRADE.md` этапы 1–3, `UPGRADE-v2.md` P12–P17, `BAGFIX_PLAN.md`
> B1–B4/S1–S8). Бэкенд отдаёт 78 роутов, UI использует ~30 — пробелы
> сгруппированы вокруг того, что делалось «под LLM-агента» и отчётной
> части для человека не получило.
>
> Меняет статус `ui/` в `CLAUDE.md` с «стенд для ручного тестирования, не
> часть продукта» на «стенд, который дорабатывается до продакшена» —
> отсюда требование юзабельности, а не только наличия вызова API.
> Правка `CLAUDE.md`/`AGENTS.md` — по завершении работ, не заранее.

## [S1] Problem

### 1.1. Результат джобы не виден нигде

`api.getJob` объявлен (`ui/src/api.js:86`) и **не вызывается ни одной
вьюхой** — экрана детали джоба не существует. `GET /jobs/{id}` отдаёт
`result_success`, `result_data`, `result_error`
(`orchestrator/models/job.py:37-51`), где `result_error` с этапа 1
`UPGRADE.md` (P2) содержит **полный traceback** упавшего workflow.
`ui/src/views/Jobs.vue:21-38` показывает только id/workflow/статус/
длительность и ссылку на сырой лог. То, ради чего делался P2, оператору
из UI недоступно: чтобы понять причину падения, он читает
неструктурированный текстовый лог целиком (P11 в реестре принятых рисков
именно поэтому и принят — но принят он был при наличии traceback в
результате, которого UI не показывает).

`ui/src/views/Logs.vue:26` — одна загрузка `GET /logs/{id}` на
`onMounted`, без обновления. Для `RUNNING`-джобы это снимок на момент
открытия: лог живой, экран мёртвый. `GET /logs/{job_id}/stream` (SSE,
`orchestrator/api/logs.py:29`) не используется — см. [S4] о том, почему
он и не может быть использован без правки аутентификации.

### 1.2. История и откат (P8) — 12 роутов, ноль вызовов

`{workflows,actions,connectors}/{name}/[code|config]/{history,history/{commit},diff,restore}`
(`orchestrator/api/workflows.py:211-262`, `actions.py:116-158`,
`connectors.py:470-513` и `578-627`) в `ui/src/api.js` отсутствуют
полностью. Это единственный путь восстановления после порчи файла и
**компенсирующий контроль принятого риска P10** (нет блокировки
параллельного редактирования — «зато есть git-история»). Из UI его нет:
оператор, перезаписавший рабочий workflow, идёт на сервер.

### 1.3. Webhook-workflow не сконфигурировать из UI (P9)

`GET /workflows` возвращает `token` (`orchestrator/api/workflows.py:96-97`),
`ui/src/views/Workflows.vue:28-52` его не выводит. Создать webhook-workflow
на стенде можно, узнать его URL и токен — нельзя, а без них внешнюю
систему не подключить и вебхук не проверить. Там же теряются
`schedule`/`interval`/`timeout`/`concurrency`/`docstring` — все приходят
в том же ответе и нигде не показаны, хотя это и есть конфигурация
запуска.

### 1.4. Роль `agent` не заводится из UI (P7)

Списки ролей захардкожены без неё: `ui/src/views/Users.vue:37-42` и
`ui/src/views/ApiKeys.vue:12-17` знают `viewer/analyst/service/admin`.
Этап 3 `UPGRADE.md` вводил роль `agent` ровно для того, чтобы агенту не
выдавали `admin` — выдать её из UI нельзя, только через API/CLI, то есть
на практике выдадут `admin`.

### 1.5. Промпты (P4) без интерфейса

`GET /prompts/system`, `GET|PUT /prompts/user`
(`orchestrator/api/prompts.py`) — в UI нет. Пользовательский промпт
редактируемый (`admin`, с git-коммитом и audit-записью
`prompt.update_user`), единственный способ его править — curl.

### 1.6. Аудит показывает не все типы ресурсов

`ui/src/views/AuditLog.vue:57`:
`const resourceTypes = ['workflow', 'action', 'connector', 'apikey', 'job']`.
Бэкенд пишет восемь: добавились `prompt`, `transfer`, `user`. Первые два
появились в S3/S4 (`BAGFIX_PLAN.md`) и P4 — то есть ровно те записи,
которые заводились под комплаенс (выгрузка всех credential'ов системы —
`transfer.export`), не выбираются фильтром. `since`/`until`
(`orchestrator/api/audit.py:37-38`) в UI тоже нет — разбор инцидента «что
происходило в интервале» делается пролистыванием страниц по 50.

### 1.7. Интроспекция (P3) не выведена

`/actions/{name}/describe`, `/connectors/{name}/describe`
(`actions.py:89`, `connectors.py:394`) не используются; `Tools.vue`
покрывает только `/tools`. Сигнатуры и докстринги коннектора видны
агенту, но не человеку, который правит его код в соседней текстареа.

### 1.8. UI не знает про роли — кнопки врут

Ни одна вьюха, кроме навигации (`App.vue:13-15`, только `admin`), не
учитывает роль. `viewer` видит Save/Delete/Run/Log и получает 403 в
`alert()`. Хуже всего с логами: `GET /logs/{id}` требует `_RW`
(`orchestrator/api/logs.py:13` — `analyst/service/admin/agent`), а кнопка
«Log» в `Jobs.vue:30` показывается всем, у кого есть `log_path`. Для
`viewer` — гарантированный 403 на самой востребованной кнопке.

Ошибки при этом обрабатываются тремя разными способами:
`error.value` (`Jobs.vue:62`), `saveResult` (`Workflows.vue:157`),
`alert()` (`Jobs.vue:69`, `Workflows.vue:190`).

## [S2] Solution — форма и границы

**Только `ui/`. Бэкенд не трогаем ни одной правкой** — все данные уже
отдаются существующими роутами. Единственное исключение, которое было бы
нужно (SSE-аутентификация), сознательно обходится ([S4]).

Работа разбита на 6 стадий, каждая самостоятельно полезна и
самостоятельно проверяема. Порядок обязателен только для стадии 0 —
остальные независимы.

| Стадия | Закрывает | Суть |
|--------|-----------|------|
| 0 | 1.8 | `permissions.js`, единый показ ошибок, vitest |
| 1 | 1.1 | Экран детали джоба: результат, traceback, живой лог |
| 2 | 1.2 | `HistoryPanel` — история/diff/откат для 3 сущностей |
| 3 | 1.3 | Деталь workflow: webhook URL+токен, расписание |
| 4 | 1.4, 1.5 | Роль `agent`, экран промптов |
| 5 | 1.6, 1.7 | Полный фильтр аудита, `describe` в Actions/Connectors |

Из скоупа исключены: редизайн (тема, layout, компонентная библиотека),
i18n, сборка/деплой UI, замена самописного `api.js` на клиент из OpenAPI.
Стиль остаётся текущим — инлайновые стили и глобальные классы из
`App.vue:42-74`; новые общие компоненты используют те же классы
(`card`/`btn`/`badge`), новых css-фреймворков не вводим.

## [S3] Стадия 0 — фундамент: права, ошибки, тесты

### `ui/src/permissions.js` — зеркало ролевых кортежей бэкенда

Единственный источник правды о ролях в UI. Списки должны буквально
повторять кортежи роутеров, с указанием файла-источника в комментарии,
чтобы расхождение ловилось глазами при ревью:

```js
export const ROLES = ['viewer', 'analyst', 'service', 'admin', 'agent']

const CAPS = {
  // orchestrator/api/workflows.py:20, actions.py:23  _ADMIN
  'code.write':       ['admin', 'agent'],
  // orchestrator/api/connectors.py:516 — литеральный ("admin",) после B3
  'connector.code.write': ['admin'],
  // orchestrator/api/connectors.py:628 — hidden-поля правит только admin
  'connector.config.write': ['admin', 'agent'],
  // orchestrator/api/logs.py:13  _RW
  'logs.read':        ['analyst', 'service', 'admin', 'agent'],
  // orchestrator/api/jobs.py:14  _RW
  'job.create':       ['analyst', 'service', 'admin', 'agent'],
  // orchestrator/api/jobs.py:15  _ANALYST
  'job.cancel':       ['analyst', 'admin', 'agent'],
  // orchestrator/api/workflows.py:19  _RW
  'workflow.reload':  ['analyst', 'admin', 'agent'],
  'restore':          ['admin', 'agent'],
  'prompt.write':     ['admin'],
  'transfer':         ['admin'],
  'audit.read':       ['admin'],
  'auth.admin':       ['admin'],
}

export function can(role, cap) {
  return (CAPS[cap] || []).includes(role)
}
```

Правило применения: **кнопка, которую роль не может нажать, не
показывается**; если скрывать нельзя (кнопка несёт смысл — например,
«Log» объясняет, что лог существует), она `disabled` с `title`,
объясняющим причину. Никаких 403 в `alert()` по действиям, которые UI
мог предсказать заранее.

Отдельный случай — `auth.noAuthMode` (`ui/src/store/auth.js:22-27`):
`secret_key` не задан, бэкенд отдаёт анонимного `admin`. `role` в сторе
уже `'admin'`, `can()` работает без спецкейса.

### Единый показ ошибок

`ui/src/components/Toast.vue` + `ui/src/store/toast.js` с
`notify.error(msg)` / `notify.success(msg)`. Все `alert()` из вьюх
убираются. Инлайновые `saveResult`-блоки под редакторами остаются — они
привязаны к месту действия и это полезно, — но текст ошибки в них
формируется тем же способом.

`api.js` при 403 добавляет в сообщение роль пользователя («Forbidden:
роль viewer не может ...») — сейчас в UI приходит голое `Forbidden`.

### Тесты

В `ui/` тестового рантайма нет вовсе (`ui/package.json:4-8` — только
`dev`/`build`/`preview`). Test-first из `CLAUDE.md` для Vue-вьюх в
полном объёме (DOM, роутер, моки fetch) — это отдельный объём работы,
несопоставимый с пользой на стенде. Компромисс, фиксируемый здесь как
решение:

- **vitest + @vue/test-utils** ставятся в `devDependencies`, скрипт
  `npm test`;
- **тестами покрывается логика, не разметка**: `permissions.js` (таблица
  прав), `api.js` (построение URL, refresh-retry, парсинг ошибок), чистые
  функции новых компонентов (сборка webhook-URL, формат diff, фильтры
  аудита);
- **вьюхи покрываются smoke-тестом монтирования** (рендерится без
  исключения при подсунутом моке api) — не проверкой верстки;
- остальное — ручной чеклист в отчёте по стадиям.

Бэкенд-тесты не трогаются: ни один роут не меняется.

## [S4] Стадия 1 — видимость исполнения (P2)

### Новый экран `/jobs/:id` — `ui/src/views/JobDetail.vue`

Секции сверху вниз:

1. **Шапка**: workflow, статус-бейдж, `triggered_by`, времена
   (`triggered_at`/`started_at`/`finished_at`), длительность, `timeout`,
   `concurrency`.
2. **Результат**: `result_success` бейджем; `result_data` — `<pre>` с
   `JSON.stringify(..., 2)`; `result_error` — `<pre>` c моноширинным
   traceback, визуально отделённый (красная рамка), **разворачивается
   по умолчанию для `failed`**. Это и есть отчётная часть P2.
3. **Context**: `job.context` (payload вебхука, `dry_run` и т.п.) —
   свёрнут по умолчанию.
4. **Лог**: содержимое `GET /logs/{id}` в `<pre>`; для `pending`/`running`
   — автообновление, см. ниже. Кнопка «Открыть в отдельной вкладке»
   ведёт на существующий `/logs/:id`.
5. **Аудит**: deep-link в `/audit-log?resource_type=job&resource_id=<id>`
   (для `admin`) — тот же паттерн, что уже используется в
   `Jobs.vue:31-32`.

### Живой лог без SSE

`GET /logs/{job_id}/stream` использовать **нельзя**: браузерный
`EventSource` не умеет отправлять заголовок `Authorization`, а
`get_current_user` (`orchestrator/auth/dependencies.py:31-35`) принимает
токен **только** из `Authorization: Bearer`. Варианты «токен в
query-параметре» или «cookie-аутентификация» — правка модели
аутентификации: токен утечёт в access-логи nginx и в audit `request`
path. Ради стенда это несоразмерно и в этот скоуп не входит.

Решение: пока `job.status ∈ {pending, running}` — перезапрашивать
`GET /jobs/{id}` и `GET /logs/{id}` раз в 2 секунды (тот же паттерн, что
уже живёт в `Jobs.vue:72` и `Status.vue:63`), останавливать таймер при
терминальном статусе и в `onUnmounted`. При смене статуса на терминальный
— один финальный запрос обоих ресурсов, чтобы не потерять последние
строки.

`GET /logs/{id}` возвращает `PlainTextResponse`
(`orchestrator/api/logs.py:26`), а `request()` в `api.js:65` всегда делает
`res.json()` — сейчас `getLogs` работает по случайности (FastAPI отдаёт
`text/plain`, `res.json()` на нём падает → ошибка ловится вьюхой). Это
надо чинить в стадии 0: `api.getLogs` должен читать `res.text()`. Иначе
лог не покажется ни на новом экране, ни на старом.

### Правки `Jobs.vue`

- Строка таблицы кликабельна → `/jobs/:id`; отдельная кнопка «Details».
- Колонка **Result**: `✓` / `✗` + первая строка `result_error` (обрезанная),
  чтобы причина падения была видна из списка без перехода.
- Кнопка «Log» — `v-if="can(auth.role, 'logs.read')"`.
- Кнопка «Cancel» — `v-if="can(auth.role, 'job.cancel')"`.
- Фильтр по статусу оставить; добавить `dry_run`-признак в строку, если
  `job.context.dry_run` — иначе прогон в dry-run неотличим от боевого.

`Logs.vue` остаётся как есть (полноэкранный просмотр), получает то же
автообновление и корректный `getLogs`.

## [S5] Стадия 2 — история и откат (P8)

### `ui/src/components/HistoryPanel.vue`

Один компонент на все три сущности; различия — в props, не в коде:

```js
props: { entity: 'workflow' | 'action' | 'connector',
         name: String,
         file: 'code' | 'config' }   // config — только для connector
```

Пути строятся таблицей, а не конкатенацией на месте — они у сущностей
разные (`actions.py:116` — `/{name}/history` без `/code`,
`workflows.py:211` — `/{name}/code/history`, `connectors.py:470,578` —
`/code/history` и `/config/history`):

```js
const PATHS = {
  workflow:        (n) => `/workflows/${n}/code`,
  action:          (n) => `/actions/${n}`,
  connector_code:  (n) => `/connectors/${n}/code`,
  connector_config:(n) => `/connectors/${n}/config`,
}
```

Поведение:

- список коммитов из `GET .../history` — `hash` (8 символов), `message`,
  `author`, `timestamp` (`orchestrator/core/history.py:4-10`), новые
  сверху, лимит 20 (дефолт бэкенда);
- клик по коммиту → `GET .../history/{commit}` → содержимое версии в
  `<pre>` read-only;
- выбор двух коммитов (радиокнопки «A»/«B») → `GET .../diff?a=&b=` →
  вывод unified diff c подсветкой `+`/`-` по первому символу строки;
  для конфигов коннектора значения hidden-полей уже замаскированы
  бэкендом (B2) — UI не пытается ничего домаскировать и не предупреждает
  об обратном;
- «Restore» → `POST .../restore` с `{commit}`, только при
  `can(role,'restore')` (для кода коннектора — `connector.code.write`,
  т.е. буквально `admin`, см. B3), с `confirm()`, после успеха —
  перезагрузка содержимого редактора и списка коммитов.

Встраивается вкладкой рядом с редактором в `Workflows.vue`,
`Actions.vue`, `Connectors.vue` (для коннектора — две панели: код и
конфиг). Редактор и история — вкладки одной карточки, не два экрана.

## [S6] Стадия 3 — конфигурация workflow и webhook (P9)

Разворачиваемая деталь строки в `Workflows.vue` (не отдельный экран):

- `docstring` — описание workflow из кода;
- для `scheduled`: `schedule` (cron) / `interval`, ближайший запуск —
  сопоставлением с `status.scheduler.next_runs`, который уже грузит
  `Status.vue:33-38`;
- `timeout`, `concurrency`;
- для `webhook`: полный URL `${location.origin}/api/webhooks/${name}` и
  токен с кнопкой «Copy» и `curl`-примером с заголовком
  `X-Webhook-Token` (`orchestrator/api/webhooks.py:28`). Токен под
  «показать/скрыть», не открытым текстом на общем экране;
- ссылка «Jobs этого workflow» → `/jobs?workflow_name=<name>`
  (фильтр в `Jobs.vue:50` уже есть, надо принять его из query).

**Замечание по периметру:** `GET /workflows` отдаёт `token` роли
`viewer` (`workflows.py:80` на `_RO`). UI, показывая токен, периметр не
расширяет — он и так доступен любому, кто открыл DevTools. Но это
самостоятельная находка бэкенда: webhook-токен — это credential уровня
«запустить произвольный workflow», а раздаётся он самой
низкопривилегированной роли. Заводится отдельным пунктом **M13** в
`docs/concepts/BAGFIX_PLAN.md` (не чинится в этом цикле — это правка
бэкенда, здесь только UI).

## [S7] Стадия 4 — роль `agent` и промпты (P7, P4)

- `Users.vue:37-42` и `ApiKeys.vue:12-17` — `<option v-for="r in ROLES">`
  из `permissions.js`, захардкоженные списки убрать. Рядом с `agent` —
  подсказка: «код и джобы, без доступа к пользователям, ключам и
  audit-log».
- Новый `/prompts` (`ui/src/views/Prompts.vue`, пункт меню виден всем —
  `GET` на `_RO`):
  - **System** — read-only `<pre>`, 404 показывается как «не настроен»,
    а не как ошибка (`prompts.py:22-25`);
  - **User** — textarea; `null` content (`prompts.py:36`) = «не задан»,
    пустое поле, не строка «null»; кнопка «Save» только при
    `can(role,'prompt.write')`; после сохранения — commit-хеш в
    `saveResult`, как в остальных редакторах; для не-admin — read-only
    без кнопки.

## [S8] Стадия 5 — аудит и интроспекция (1.6, 1.7)

**Аудит** (`AuditLog.vue`):

- `resourceTypes` = все восемь, что пишет бэкенд: `workflow`, `action`,
  `connector`, `apikey`, `job`, `prompt`, `transfer`, `user` (проверено
  grep'ом по `resource_type=` в `orchestrator/`);
- фильтры `since`/`until` (`<input type="datetime-local">` →
  ISO в query, `orchestrator/api/audit.py:37-38`);
- быстрые пресеты периода: час / сутки / неделя;
- `detail` сейчас выводится как `JSON.stringify` в одну строку
  (`AuditLog.vue:37`) — сделать разворачиваемым `<pre>`;
- если `detail.commit` присутствует — ссылка в `HistoryPanel`
  соответствующей сущности на этот коммит (замыкает аудит на историю:
  «кто изменил» → «что именно изменилось»).

**Интроспекция**: кнопка «Signature» в `Actions.vue` и `Connectors.vue` →
`GET /{name}/describe` → имя, докстринг, параметры с типами и дефолтами;
для коннектора — список методов (тот же формат, что уже рендерит
`Tools.vue:29-37`, переиспользовать разметку).

## [S9] Testing Strategy

Юнит (vitest, `ui/tests/`):

- `permissions.spec.js` — таблица прав: для каждой из 5 ролей проверить
  весь набор capability; отдельно — что `viewer` не получает
  `logs.read`, а `agent` не получает `connector.code.write`,
  `prompt.write`, `audit.read`, `auth.admin` (это ровно те сужения, что
  вводили B3 и этап 3 `UPGRADE.md`);
- `api.spec.js` — `getLogs` возвращает текст, а не падает на `res.json()`;
  401 → один retry через `/auth/refresh` → повтор исходного запроса;
  повторный 401 → `clearTokens` + `onUnauthorized`; 403 → сообщение с
  ролью;
- `history-paths.spec.js` — таблица `PATHS` даёт корректные URL для
  четырёх комбинаций entity/file;
- `webhook-url.spec.js` — сборка URL и `curl`-примера;
- smoke-монтирование новых вьюх (`JobDetail`, `Prompts`) и
  `HistoryPanel` с моком `api`.

Ручной чеклист (в отчёт, на стенде с включённой auth):

1. Упавший workflow → `/jobs/:id` показывает traceback целиком, без
   похода в лог.
2. Запущенный workflow → лог на экране детали дописывается сам, таймер
   останавливается на терминальном статусе (проверить в Network, что
   опрос прекратился).
3. Сломать workflow → откатиться из `HistoryPanel` → workflow снова в
   реестре, в `/audit-log` есть `workflow.restore`.
4. Webhook-workflow → скопировать URL+токен из UI, дёрнуть `curl`'ом →
   джоба создалась, в аудите `job.create` с `actor_type` вебхука.
5. Залогиниться `viewer` → не видно кнопок Save/Delete/Run/Log, ни одного
   403 в интерфейсе; залогиниться `analyst` → лог читается, код не
   правится.
6. Выдать API-ключ роли `agent` из UI → ключ работает на `PUT
   /workflows/{name}/code` и получает 403 на `/audit-log`.
7. `/audit-log` с фильтром `resource_type=transfer` и периодом за сутки
   показывает запись экспорта.

## [S10] Success Criteria

- [ ] Причина падения джобы видна из UI без чтения сырого лога
      (traceback из `result_error` на экране детали)
- [ ] Лог выполняющейся джобы обновляется сам и перестаёт опрашиваться
      после завершения
- [ ] Для workflow, action и коннектора (код и конфиг) из UI доступны
      история, просмотр версии, diff и откат
- [ ] Webhook-workflow полностью настраивается из UI: URL, токен, пример
      вызова
- [ ] Роль `agent` выдаётся из UI и пользователю, и API-ключу
- [ ] Системный и пользовательский промпт видны, пользовательский
      редактируется admin'ом
- [ ] Фильтр аудита покрывает все 8 типов ресурсов и интервал времени
- [ ] Ни одно действие, недоступное роли, не предлагается интерфейсом —
      403 в UI не возникает по предсказуемым причинам
- [ ] `npm test` зелёный; бэкенд-тесты не затронуты (`pytest` без
      изменений относительно базового прогона)
- [ ] Ни одной правки в `orchestrator/` и `soar/`
