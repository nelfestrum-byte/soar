# Report: Monaco-редактор кода вместо `<textarea>`

Spec: `docs/compose/specs/2026-08-06-monaco-editor-design.md`
Plan: `docs/compose/plans/2026-08-06-monaco-editor.md`

## What was built

- `ui/src/monaco-setup.js` (new) — единая точка загрузки Monaco, `loadMonaco()`
  как в спеке [S3]: ленивый `import('monaco-editor/editor/editor.api')`,
  `MonacoEnvironment.getWorker` на `?worker`-импорт `editor.worker`,
  мемоизация промиса. **Отличие от спеки:** subpath не
  `monaco-editor/esm/vs/editor/editor.api`, а `monaco-editor/editor/editor.api`
  (без `/esm/vs/`) — установленный `monaco-editor@0.56.0` объявляет в
  `package.json` `exports` только `"./*": "./esm/vs/*.js"`, поэтому путь из
  спеки (написанной до фиксации версии) не резолвится вообще (ни в Vite, ни
  в Node): `esm/vs/editor/editor.api` подставляется в `*` и даёт
  `esm/vs/esm/vs/editor/editor.api.js`, которого не существует. Правильный
  subpath под текущий exports-map — `editor/editor.api` →
  `esm/vs/editor/editor.api.js`. Тот же сдвиг применён к
  `editor/editor.worker?worker`. Никакой строки с `cdn`/`unpkg`/`jsdelivr`.
- `ui/src/components/CodeEditor.vue` (new) — как в спеке [S4]: пропсы
  `modelValue`/`language`/`readOnly`/`height`, событие `update:modelValue`,
  `onMounted` создаёт редактор через `loadMonaco()`, `watch` на `modelValue`
  (с сравнением `val !== editor.getValue()` — защита от цикла) и `readOnly`
  (`updateOptions`), `onUnmounted` → `dispose()`. Корневой
  `<div data-test="code-editor">`.
- Подключение в пяти местах из таблицы [S5]: `Workflows.vue:103`,
  `Actions.vue:52`, `Connectors.vue:57` (код, `language="python"`) и
  `Connectors.vue:113` (конфиг, `language="yaml"` — не `json`, см. [S1] про
  исправление неточности `UI-REDESIGN.md:104`), `Prompts.vue:23`
  (`language="plaintext"`, сохранён существующий
  `data-test="user-prompt-editor"` вместо `code-editor`, как и планировалось
  в части E плана). `Workflows.vue:118` (run-payload) не тронут — вне скоупа
  по [S2].

## Tests

Test-first по плану: `code-editor.spec.js` и новые проверки в
`editor-toolbar.spec.js`/`prompts.spec.js` были написаны и запущены красными
до реализации `CodeEditor.vue` (`Failed to resolve import` до установки
пакета/фикса subpath, затем `expected false to be true` до подключения
компонента во вьюхах), только потом сделана реализация.

- `ui/tests/setup.js` (modified) — `vi.mock('monaco-editor/editor/editor.api', ...)`
  с фейковым `editor.create()`: возвращает стаб с `getValue`/`setValue`
  (общее замыкание над `value`), `onDidChangeModelContent` (сохраняет
  колбэк через `vi.fn()`), `updateOptions`/`dispose`/`layout`. Тест-файлы
  получают доступ к стабу через `monaco.editor.create.mock.results` —
  никакого отдельного экспорта не потребовалось.
- `ui/tests/code-editor.spec.js` (new, 6 тестов) — создание с
  value/language/readOnly, эмит `update:modelValue` при вызове сохранённого
  колбэка, `setValue` при внешнем изменении `modelValue`, **не**-`setValue`
  при том же значении (защита от цикла), `updateOptions({readOnly})` при
  смене пропса, `dispose()` на unmount.
- `ui/tests/editor-toolbar.spec.js` (modified) — в каждый из трёх
  существующих тестов (Workflows/Actions/Connectors) добавлена проверка
  `[data-test="code-editor"]`; тест Connectors дополнительно проверяет
  `wrapper.findComponent(CodeEditor).props('language') === 'yaml'` после
  переключения на вкладку Config.
- `ui/tests/prompts.spec.js` (modified) — два теста, ранее читавшие DOM
  `<textarea>` напрямую (`.element.value`, `.attributes('readonly')`),
  переписаны на `wrapper.findComponent(CodeEditor).props(...)`, так как
  `CodeEditor` в тестах — компонент поверх мокнутого Monaco, а не настоящий
  `<textarea>`, и `readOnly`/содержимое видны только через пропсы, не через
  DOM-атрибуты стаба.

Run: `cd ui && npx vitest run` → **16 test files passed, 85 tests passed**
(было 79 тестов в 15 файлах до этой работы; +6 новых в `code-editor.spec.js`,
остальные — расширенные проверки внутри существующих `it`-блоков, без роста
их числа).

## Manual verification ([S6] ручной чеклист)

Поднят реальный стенд: `python -m uvicorn orchestrator.main:app --port 8000`
(anonymous admin, `auth.secret_key` не задан) + `cd ui && npm run dev`, живая
проверка через Playwright-браузер (не unit-тесты):

1. **Python-подсветка + автозакрытие/номера строк** — подтверждено
   скриншотом на реальном воркфлоу (`from soar.workflows.base import
   ScheduledWorkflow`, `class SmokeTest(ScheduledWorkflow):` и т.д.):
   ключевые слова/классы/строки/комментарии раскрашены, гутер с номерами
   строк на месте.
2. **YAML-подсветка конфига коннектора** — подтверждено косвенно: юнит-тест
   `editor-toolbar.spec.js` проверяет `language === 'yaml'` именно в той
   ветке шаблона (`configTab==='config'`, `rawConfigMode`), которая рендерит
   `CodeEditor` для конфига; вживую этот путь (raw-YAML-режим) требует
   коннектора без полей схемы — все зашитые в `soar/connectors/*` коннекторы
   имеют хотя бы `instance_name` в схеме, поэтому Setup всегда открывает
   форму, не raw-редактор, в рамках доступных на стенде данных. Тот же
   компонент/тот же вызов `monaco.editor.create` с `language` из пропа уже
   визуально подтверждён на Python-панели — риск того, что именно `yaml` как
   строковый параметр не сработает, отдельно от общего пути не оценивается.
3. **`viewer` не может печатать** — подтверждено юнит-тестами
   (`code-editor.spec.js`: `updateOptions({readOnly: true})` вызывается;
   `prompts.spec.js`: `props('readOnly') === true` для `viewer`,
   `=== false` для `admin`). Живая проверка не проводилась — локальный
   стенд поднят с `auth.secret_key` не задан → anonymous admin, роль
   `viewer` недостижима без полноценной настройки auth.
4. **Air-gap** — проверено на уровне трафика, не только grep по исходникам:
   `browser_network_requests` за весь сеанс (навигация по Workflows/
   Connectors/Prompts, создание тестового workflow/connector, открытие
   Monaco с реальным содержимым) — **все запросы к `127.0.0.1:5173`**
   (dev-сервер, включая `node_modules/monaco-editor/esm/vs/**` и воркер),
   ни одного к внешнему хосту. `grep -rn "cdn\.|jsdelivr|unpkg" ui/src` —
   пусто (единственное совпадение было в собственном комментарии
   `monaco-setup.js` — переформулирован, чтобы не давать ложных срабатываний
   будущим grep-проверкам).
5. **Переключение сущностей обновляет контент** — подтверждено вживую:
   открыт workflow с ошибкой загрузки (`Error: Workflow not found` —
   несвязанная с этой задачей рассинхронизация тестовых данных стенда),
   закрыт, создан и открыт новый workflow — редактор показал новый реальный
   код, не старое сообщение об ошибке.

Тестовые артефакты (workflow `SmokeTest`, connector `smoke_test`), созданные
для проверки, удалены через API после проверки; скриншоты не сохранены в
репозитории.

## Non-goals confirmed untouched

Per [S2]: `Workflows.vue:118` (run-payload) и `Generate.vue:13` (вставка
OpenAPI-спеки) остались на `<textarea>` — `grep -rn "textarea"
ui/src/views/Workflows.vue ...` даёт единственное совпадение,
`Workflows.vue:118`. `HistoryPanel.vue` diff-view не тронут. Ни одной правки
в `orchestrator/`/`soar/`.

## `npm run build`

`cd ui && npm run build` — успешно. Monaco лениво code-split в отдельные
чанки (`editor.api-*.js` ~2.6 MB, `editor.worker-*.js` ~273 KB), не в
основном бандле — подтверждает лениво загружаемую архитектуру из [S2].4.
Chunk-size warning от Rollup — ожидаемый (Monaco всегда большой), не
регрессия.

## Docs

- `docs/concepts/UI-REDESIGN.md` — чеклист: Часть 5.4 отмечена выполненной
  (diff-editor в `HistoryPanel` — отдельно, остаётся открытым вместе с
  5.3).
- `CLAUDE.md` — абзац про `UI-REDESIGN.md` обновлён: 5.4 реализована
  2026-08-06, текущий UI больше не «по-прежнему на `<textarea>`» для пяти
  редакторов сущностей.

## Files changed

- `ui/src/monaco-setup.js` (new)
- `ui/src/components/CodeEditor.vue` (new)
- `ui/src/views/Workflows.vue` (modified)
- `ui/src/views/Actions.vue` (modified)
- `ui/src/views/Connectors.vue` (modified)
- `ui/src/views/Prompts.vue` (modified)
- `ui/tests/setup.js` (modified)
- `ui/tests/code-editor.spec.js` (new)
- `ui/tests/editor-toolbar.spec.js` (modified)
- `ui/tests/prompts.spec.js` (modified)
- `ui/package.json` / `ui/package-lock.json` (modified — `monaco-editor` dependency)
- `docs/concepts/UI-REDESIGN.md` (modified — 5.4 checklist)
- `CLAUDE.md` (modified — UI-REDESIGN status paragraph)
- `docs/compose/specs/2026-08-06-monaco-editor-design.md` (pre-existing)
- `docs/compose/plans/2026-08-06-monaco-editor.md` (pre-existing)
- `docs/compose/reports/monaco-editor.md` (this file)
