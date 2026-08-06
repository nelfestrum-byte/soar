# Monaco-редактор кода вместо `<textarea>`

> Реализует Стадию 5.4 из [`docs/concepts/UI-REDESIGN.md`](../../concepts/UI-REDESIGN.md)
> (Часть 2, «Целевой UX редактирования: Monaco, не полноценный VS Code Web»),
> которая была спланирована 2026-07-31, но осталась открытой — см. отметку в
> `CLAUDE.md`. Полный визуальный редизайн (навигация, layout, список сущностей
> в боковую панель) — отдельная будущая работа без спека и плана на момент
> написания этого документа. Эта спека решает редактор отдельно и раньше,
> поэтому граница [S2] здесь важнее обычного: компонент не должен знать о
> карточках/вкладках, в которые он сейчас встроен, чтобы редизайн не
> потребовал его переписывать.

## [S1] Problem

`docs/concepts/UI-REDESIGN.md:64-73` (V4) уже зафиксировал проблему:
редактирование кода workflow/action/connector/промпта — везде один и тот же
`<textarea>` без подсветки синтаксиса, номеров строк и автозакрытия скобок.
Подтверждено по коду — шесть мест:

| Файл | Строка | Сущность | Формат |
|------|--------|----------|--------|
| `Workflows.vue` | 103 | код workflow | Python |
| `Actions.vue` | 52 | код action | Python |
| `Connectors.vue` | 57 | код connector | Python |
| `Connectors.vue` | 113 | конфиг connector | **YAML** |
| `Prompts.vue` | 23 | user prompt | текст |
| `Workflows.vue` | 118 | payload запуска джобы | JSON, ad hoc форма |
| `Generate.vue` | 13 | вставка OpenAPI-спеки | JSON/YAML, разовый ввод |

Про формат конфига коннектора: `UI-REDESIGN.md:104` ошибочно называет его
JSON. Бэкенд работает с YAML (`orchestrator/api/connectors.py` —
`pyyaml.safe_load`/`safe_dump`, `_redact_yaml`) — спек ниже фиксирует
правильный язык, чтобы не унаследовать неточность в код.

Diff в `HistoryPanel.vue:38-39` — тот же вопрос, но отдельный: сейчас это
текст с раскраской по первому символу строки, Monaco дал бы `DiffEditor`
(сравнение бок-о-бок). Не входит в эту спеку — см. границы [S2].

Два дополнительных условия зафиксированы в разговоре, до написания спека:

1. **Редизайн — отдельно и позже, план не написан.** Компонент редактора не
   должен зависеть от текущей структуры карточки (`.card` под таблицей,
   вкладки Code/History) сильнее, чем необходимо — иначе редизайн, переносящий
   список сущностей в боковую панель, будет вынужден трогать код редактора,
   а не просто переставлять его в новый layout.
2. **Air-gap.** `CLAUDE.md`, принцип 4: «зависимости запекаются в образ...
   установки пакетов в рантайме нет». Популярные Vue-обёртки над Monaco
   (`@guolao/vue-monaco-editor`, аналоги `@monaco-editor/react`) по умолчанию
   используют `@monaco-editor/loader`, который тянет Monaco с CDN
   (`cdn.jsdelivr.net`), если не переопределить loader явно. Это тихо
   ломает offline-стенд и не покрывается тестами, запущенными на машине
   с интернетом — требование «без CDN» нужно закрыть архитектурно, а не
   надеяться на то, что кто-то не забудет прописать конфиг.

## [S2] Solution — форма и границы

**В скоуп** входит один переиспользуемый компонент и его подключение в
пяти местах из таблицы [S1] (все, кроме run-payload и Generate.vue — см.
ниже).

**Вне скоупа, явно и с обоснованием:**

- **`Workflows.vue:118`** (payload для запуска джобы) — разовая форма
  ввода JSON для конкретного запуска, не редактирование сущности с
  историей/git. Не входила в исходный список V4. Остаётся `<textarea>`.
- **`Generate.vue:13`** (вставка OpenAPI-спеки) — то же самое: разовый
  вход в конвертер, не round-trip редактирование файла сущности. Не
  входила в V4. Остаётся `<textarea>`.
- **`HistoryPanel.vue` diff-view** — переиспользует тот же загрузчик
  (`monaco-setup.js`, [S3]), но это отдельная фича (`DiffEditor`, два
  контента вместо одного) с собственным объёмом тестирования. Явный
  следующий шаг после этой спеки, не часть неё — чтобы объём остался
  проверяемым за один заход.
- **Семантический автокомплит Python** (LSP уровня Pyright/Jedi) — Monaco
  из коробки даёт Monarch-подсветку, автозакрытие скобок/кавычек и
  word-based автодополнение (предлагает слова, уже встреченные в
  документе) — не понимание типов/импортов. Это ровно то отличие, которое
  `UI-REDESIGN.md:92-97` зафиксировал заранее («не полноценный VS Code
  Web») — здесь просто явно проговорено, чтобы не было ожидания
  IntelliSense там, где его не будет.

### Архитектурные принципы (гибкость под будущий редизайн)

1. **`CodeEditor.vue` — layout-agnostic leaf-компонент.** Пропсы на входе
   (`modelValue`, `language`, `readOnly`, `height`), событие на выходе
   (`update:modelValue`). Никакого знания о карточках, вкладках, сайдбаре.
   Будущий редизайн переставляет компонент в новый layout, не переписывает
   его.
2. **Прямая работа с пакетом `monaco-editor`, без Vue-обёртки.** Обёртки
   (`@guolao/vue-monaco-editor` и подобные) навязывают свой лоадер и свой
   жизненный цикл — а именно лоадер и есть источник CDN-риска из [S1].
   Прямая интеграция даёт полный контроль над загрузкой и не заставляет
   бороться с чужой абстракцией, когда позже понадобится `DiffEditor`.
3. **Вся конфигурация загрузки — в одном файле**, `ui/src/monaco-setup.js`
   ([S3]). Если офлайн-требование изменится или понадобится новый язык —
   правка в одном месте, не по всем вьюхам.
4. **Ленивая загрузка.** `monaco-editor` — несколько мегабайт; не должен
   попасть в основной бандл. `CodeEditor.vue` грузит его через
   `import()` в `onMounted` — Vite делает code-splitting сам.
5. **`language`/`readOnly` — реактивные пропсы**, контент управляется
   снаружи через `v-model` без дублирования состояния внутри компонента.
6. **Диспоуз на размонтирование.** Карточки редактора сейчас монтируются
   через `v-if` при каждом открытии/закрытии (`editMode`/`codeTab` и т.п.)
   — без явного `dispose()` инстансы Monaco будут копиться в памяти за
   сессию.

## [S3] `ui/src/monaco-setup.js`

Единая точка загрузки, без CDN. Для python/yaml/plaintext отдельные
language-воркеры не нужны — они не заявлены Monaco (в отличие от
json/css/html/typescript) и используют только базовый `editor.worker` для
обычных сервисов (поиск, подсветка совпадений скобок). Это же снимает
вопрос о `vite-plugin-monaco-editor` — он не нужен ровно потому, что для
наших трёх языков достаточно официального ручного паттерна для Vite:

```js
// ui/src/monaco-setup.js
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

let monacoPromise = null

export function loadMonaco() {
  if (!monacoPromise) {
    monacoPromise = import('monaco-editor/esm/vs/editor/editor.api').then((monaco) => {
      self.MonacoEnvironment = {
        getWorker: () => new EditorWorker(),
      }
      return monaco
    })
  }
  return monacoPromise
}
```

`?worker` — встроенная возможность Vite (без плагинов), сама бандлит файл
воркера отдельным чанком и отдаёт с того же origin, что и остальной UI.
Никакой строки с `cdn`/`unpkg`/`jsdelivr` в кодовой базе не появляется —
это и есть проверяемое условие офлайн-требования из [S1].

`ui/package.json` — добавить `monaco-editor` (`^0.56.0`, последняя стабильная
на момент написания) в `dependencies` (не `devDependencies` — используется в
рантайме).

## [S4] `ui/src/components/CodeEditor.vue`

| Проп | Тип | Дефолт | Смысл |
|------|-----|--------|-------|
| `modelValue` | String | обязателен | содержимое файла |
| `language` | String | `'plaintext'` | `'python'` / `'yaml'` / `'plaintext'` |
| `readOnly` | Boolean | `false` | зеркалит текущий `:readonly` |
| `height` | String | `'400px'` | сохраняет текущие визуальные размеры карточек |

Событие: `update:modelValue`.

Поведение:

- `onMounted`: `await loadMonaco()` → `monaco.editor.create(container.value, { value: props.modelValue, language: props.language, readOnly: props.readOnly, automaticLayout: true, minimap: { enabled: false }, tabSize: 4, scrollBeyondLastLine: false })`. `automaticLayout: true` — редактор сам подстраивается под контейнер при ресайзе, это и есть основа для «переставит в сайдбар без правок компонента».
- `editor.onDidChangeModelContent(() => emit('update:modelValue', editor.getValue()))`.
- `watch(() => props.modelValue, (val) => { if (editor && val !== editor.getValue()) editor.setValue(val) })` — только при внешнем изменении (переключение на другую сущность без пересоздания компонента); сравнение с текущим значением редактора обязательно, иначе цикл с событием выше.
- `watch(() => props.readOnly, (val) => editor?.updateOptions({ readOnly: val }))`.
- `onUnmounted`: `editor?.dispose()`.
- Корневой элемент: `<div ref="container" class="code-editor" :style="{ height }" data-test="code-editor"></div>` — `data-test` по тому же соглашению, что уже используется в `HistoryPanel.vue`/`Prompts.vue`.

## [S5] Подключение по вьюхам

| Вьюха | Строка (сейчас) | `language` | `height` | `readOnly` источник |
|-------|------------------|-----------|----------|----------------------|
| `Workflows.vue` | 103 | `python` | `400px` | `!canWrite` |
| `Actions.vue` | 52 | `python` | `400px` | `!canWrite` |
| `Connectors.vue` (код) | 57 | `python` | `400px` | `!canWriteCode` |
| `Connectors.vue` (конфиг) | 113 | `yaml` | `200px` | `!canWriteConfig` |
| `Prompts.vue` | 23 | `plaintext` | `300px` | `!canWrite` |

Замена — прямая: `<textarea v-model="content" :readonly="!canWrite" style="...">`
→ `<CodeEditor v-model="content" language="python" height="400px" :readOnly="!canWrite" />`.
Остальная разметка карточек (toolbar, Save/Close, вкладки) не меняется —
это и есть проверка принципа [S2].2 на практике: редактор встраивается, не
перестраивая вокруг себя ничего.

## [S6] Testing Strategy

Настоящий `monaco-editor` в jsdom не запускается предсказуемо (нет `Worker`
в части конфигураций, нет полноценного canvas для измерения текста) — это
типовая проблема, решение типовое: мокать модуль в тестах, не пытаться
гонять реальный Monaco под vitest.

- **`ui/tests/setup.js`** — добавить `vi.mock('monaco-editor/esm/vs/editor/editor.api', factory)`
  с минимальной фейковой реализацией (`editor.create()` возвращает объект с
  `getValue`/`setValue`/`onDidChangeModelContent`/`updateOptions`/`dispose`/
  `layout`). Это нужно, чтобы существующие smoke-тесты
  (`editor-toolbar.spec.js`, любые, монтирующие `Workflows`/`Actions`/
  `Connectors`/`Prompts` и открывающие редактор) не пытались грузить
  настоящий Monaco и не падали на отсутствующем `Worker`.
- **`ui/tests/code-editor.spec.js`** (новый, test-first) — тестирует
  `CodeEditor.vue` поверх того же мока:
  - создаёт editor с переданными `modelValue`/`language`/`readOnly`;
  - эмитит `update:modelValue`, когда мок вызывает зарегистрированный
    `onDidChangeModelContent`-колбэк;
  - вызывает `updateOptions({readOnly})` при изменении пропса `readOnly`;
  - вызывает `setValue`, когда `modelValue` меняется снаружи и отличается
    от текущего значения редактора — и **не** вызывает, когда значение то
    же самое (тест на защиту от цикла из [S4]);
  - вызывает `dispose()` в `onUnmounted`.
- **Существующие тесты**, где селектор искал именно `textarea` внутри
  редактора (не только `.editor-toolbar`) — переключить на
  `[data-test="code-editor"]`.

Ручной чеклист (в отчёт):

1. Код workflow/action/connector — подсветка Python, автозакрытие скобок,
   номера строк.
2. Конфиг коннектора — подсветка YAML, не JSON.
3. Роль `viewer` — редактор некликабелен для ввода (`readOnly`).
4. `npm run build && npm run preview`, сеть отключена (или домены
   `jsdelivr`/`unpkg` заблокированы в DevTools) — редактор открывается и
   работает. Это прямая проверка требования [S1].2 (air-gap), а не
   формальность — без неё регресс на CDN-загрузку не будет пойман никаким
   автотестом.
5. Переключение между двумя сущностями подряд без закрытия карточки —
   содержимое редактора обновляется на новое, старое не остаётся видно.

## [S7] Success Criteria

- [ ] `CodeEditor.vue` — единственный компонент редактирования кода,
      используется во всех пяти местах таблицы [S5]
- [ ] Нет ни одной строки с CDN-адресом Monaco в кодовой базе; сборка
      работает без сети (ручная проверка [S6].4)
- [ ] `readOnly` отражает те же права, что раньше `:readonly` на `<textarea>`
- [ ] Конфиг коннектора подсвечивается как YAML, не JSON
- [ ] `HistoryPanel` diff-view не тронут (осознанно, следующий шаг)
- [ ] `npm test` зелёный, включая новый `code-editor.spec.js`
- [ ] Ни одной правки в `orchestrator/`/`soar/`
- [ ] `CodeEditor.vue` не содержит допущений о карточках/вкладках/сайдбаре
      текущего layout (проверяется ревью, не тестом) — критерий того, что
      будущий редизайн сможет переставить компонент, не переписывая его
