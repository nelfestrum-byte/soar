# Plan: Monaco-редактор кода вместо `<textarea>`

Спека: `docs/compose/specs/2026-08-06-monaco-editor-design.md`.

**Порядок:** Часть A обязательно первая — без мока и `CodeEditor.vue` части
B-E писать не на чем. Части B/C/D/E между собой независимы, можно в любом
порядке.

---

## Часть A — загрузчик и компонент

### Тесты первыми

- [ ] `ui/tests/setup.js` — добавить `vi.mock('monaco-editor/esm/vs/editor/editor.api', ...)`:
      фейковый `editor.create()` возвращает объект-стаб с полями
      `getValue`, `setValue`, `onDidChangeModelContent` (сохраняет колбэк,
      чтобы тест мог его дёрнуть вручную), `updateOptions`, `dispose`,
      `layout` — все как `vi.fn()`, с сохранением последнего переданного
      значения там, где это нужно для проверок ниже. Экспортировать сам мок
      (или доступ к последнему созданному стабу) так, чтобы
      `code-editor.spec.js` мог его импортировать и дёргать колбэки.
- [ ] `ui/tests/code-editor.spec.js` (новый файл) — падающие тесты до
      реализации компонента:
      - `it('creates the editor with the given value, language and readOnly')`
      - `it('emits update:modelValue when the editor content changes')` —
        дёрнуть сохранённый `onDidChangeModelContent`-колбэк с новым
        значением, проверить `wrapper.emitted('update:modelValue')`.
      - `it('calls setValue when modelValue prop changes externally')` —
        `await wrapper.setProps({ modelValue: 'new' })`, ожидать вызов
        `setValue('new')`.
      - `it('does not call setValue when modelValue prop equals the editor value')` —
        защита от цикла из спека [S4].
      - `it('calls updateOptions({readOnly}) when readOnly prop changes')`.
      - `it('disposes the editor on unmount')` — `wrapper.unmount()` →
        `dispose` вызван.
- [ ] Прогнать `cd ui && npm test -- code-editor` — все новые тесты
      падают (компонента ещё нет).

### Implementation

- [ ] `ui/package.json` — добавить `monaco-editor` (`^0.56.0`) в
      `dependencies`; `npm install`.
- [ ] `ui/src/monaco-setup.js` — `loadMonaco()` из спека [S3]: ленивый
      `import('monaco-editor/esm/vs/editor/editor.api')`,
      `MonacoEnvironment.getWorker` на `editor.worker?worker`,
      мемоизация промиса. Никаких строк с `cdn`/`unpkg`/`jsdelivr`.
- [ ] `ui/src/components/CodeEditor.vue` — пропсы (`modelValue`,
      `language='plaintext'`, `readOnly=false`, `height='400px'`), событие
      `update:modelValue`, поведение из спека [S4] (создание в
      `onMounted`, watch на `modelValue`/`readOnly`, `dispose` в
      `onUnmounted`), корневой `<div data-test="code-editor">`.
- [ ] `cd ui && npm test -- code-editor` — зелёный.

---

## Часть B — `Workflows.vue`

### Тесты первыми

- [ ] `ui/tests/editor-toolbar.spec.js` — тест «renders a sticky toolbar
      with tabs and Save/Close once a workflow is opened»: добавить
      проверку `wrapper.find('[data-test="code-editor"]').exists() === true`
      рядом с существующими проверками текста toolbar. Падает, пока в
      `Workflows.vue` остаётся `<textarea>`.
- [ ] Если есть тест, дёргающий сохранение workflow через ввод в
      `textarea` (`find('textarea').setValue(...)`) — найти в `ui/tests/`
      и переписать на эмит `update:modelValue` через
      `find('[data-test="code-editor"]')` + `vm.$emit` (компонент из мока,
      реальных DOM-событий ввода у стаба нет).

### Implementation

- [ ] `Workflows.vue` — импортировать `CodeEditor`, заменить `<textarea>`
      на строке 103 на `<CodeEditor v-model="content" language="python"
      height="400px" :readOnly="!canWrite" />` (спек [S5]).
- [ ] `Workflows.vue:118` (run-payload) — **не трогать**, явно вне скоупа
      (спек [S2]).
- [ ] `cd ui && npm test` — зелёный.

---

## Часть C — `Actions.vue`

### Тесты первыми

- [ ] `ui/tests/editor-toolbar.spec.js` — тест «renders a sticky toolbar
      once an action is opened»: добавить проверку наличия
      `[data-test="code-editor"]`.

### Implementation

- [ ] `Actions.vue:52` — заменить `<textarea>` на `<CodeEditor
      v-model="content" language="python" height="400px"
      :readOnly="!canWrite" />`.
- [ ] `cd ui && npm test` — зелёный.

---

## Часть D — `Connectors.vue` (код + конфиг)

### Тесты первыми

- [ ] `ui/tests/editor-toolbar.spec.js` — тест «renders a sticky toolbar
      for both code and config panels of a connector»: после клика на
      `.btn-primary` (код) — `[data-test="code-editor"]` существует; после
      клика на `.btn-success` (конфиг) — тоже существует (уже два разных
      инстанса `CodeEditor` в разных вкладках).
- [ ] Новый или расширенный тест — проверить, что конфиг-редактор получает
      `language="yaml"` (например, через проверку пропа смонтированного
      `CodeEditor` компонента: `wrapper.findComponent(CodeEditor).props('language')`
      после переключения на вкладку Config).

### Implementation

- [ ] `Connectors.vue:57` (код) — `<CodeEditor v-model="codeContent"
      language="python" height="400px" :readOnly="!canWriteCode" />`.
- [ ] `Connectors.vue:113` (конфиг) — `<CodeEditor v-model="configContent"
      language="yaml" height="200px" :readOnly="!canWriteConfig" />` —
      **язык `yaml`, не `json`** (спек [S1] — исправление неточности
      `UI-REDESIGN.md:104`).
- [ ] `cd ui && npm test` — зелёный.

---

## Часть E — `Prompts.vue`

### Тесты первыми

- [ ] `ui/tests/prompts.spec.js` — существующие тесты, ищущие
      `[data-test="user-prompt-editor"]` (`textarea`) — перевести на
      `[data-test="code-editor"]` (переносим `data-test` с `<textarea>` на
      `<CodeEditor>` — сам атрибут остаётся на компоненте, значение то
      же). Проверить, что тест сохранения (`save-user-prompt`) по-прежнему
      находит и меняет контент через новый компонент.

### Implementation

- [ ] `Prompts.vue:23` — заменить `<textarea>` на `<CodeEditor
      v-model="userContent" language="plaintext" height="300px"
      :readOnly="!canWrite" data-test="user-prompt-editor" />` (сохраняем
      существующий `data-test`, чтобы не расходиться с уже устоявшимся
      именованием в этой вьюхе — не `code-editor`, как в остальных).
- [ ] `cd ui && npm test` — зелёный.

---

## Verification

- [ ] `cd ui && npm test` — все тесты (старые и новые) зелёные
- [ ] `grep -rn "cdn\.\|jsdelivr\|unpkg" ui/src` — пусто
- [ ] `cd ui && npm run build && npm run preview` — ручной чеклист из
      спека [S6]:
      1. Python-подсветка и автозакрытие скобок в редакторах кода
      2. YAML-подсветка в конфиге коннектора
      3. `viewer` не может печатать в редакторе
      4. Сеть отключена (или домены Monaco CDN заблокированы в DevTools) —
         редактор всё равно открывается и работает
      5. Переключение между сущностями обновляет контент редактора
- [ ] `grep -rn "textarea" ui/src/views/Workflows.vue ui/src/views/Actions.vue
      ui/src/views/Connectors.vue ui/src/views/Prompts.vue` — остался
      только `Workflows.vue:118` (run-payload, осознанно вне скоупа)
- [ ] Ни одной правки в `orchestrator/`/`soar/`
- [ ] Написать отчёт `docs/compose/reports/monaco-editor.md`, отметить в
      `docs/concepts/UI-REDESIGN.md` стадию 5.4 как выполненную и обновить
      формулировку в `CLAUDE.md` (после завершения работ, не заранее — см.
      правило в `CLAUDE.md`)
