# Plan: UI-редизайн, Часть 3 — структурные стадии

Спека: `docs/compose/specs/2026-07-31-ui-redesign-structural-design.md`.
Источник: `docs/concepts/UI-REDESIGN.md`, Часть 3.

**Порядок:** Стадия A (токены) первая — остальные стадии переиспользуют
`var(--...)` из неё в новых стилях (например `.editor-toolbar` в Стадии D,
`.row-menu-panel` в Стадии C). B/C/D/E между собой независимы, можно в
любом порядке или параллельно.

Часть 4 (Google Stitch) выполняется пользователем параллельно вне этого
плана — не блокирует ни одну из стадий A-E.

---

## Часть A — `tokens.css`

### Тесты первыми (`ui/tests/tokens.spec.js`, новый файл)

- [ ] `test('tokens.css defines every semantic color used by the app')` —
      парсит `ui/src/styles/tokens.css`, проверяет наличие всех имён
      переменных из спека [S3] (`--color-surface`, `--color-surface-alt`,
      `--color-surface-dark`, `--color-surface-hover`, `--color-text`,
      `--color-text-muted`, `--color-text-faint`, `--color-text-on-dark`,
      `--color-border`, `--color-border-subtle`, `--color-accent`,
      `--color-accent-fg`, `--color-danger`, `--color-success`,
      `--color-result-ok`, `--color-result-fail`, шесть пар
      `--status-{pending,running,completed,failed,cancelled,timeout}-{bg,fg}`,
      `--space-1..6`, `--radius`, `--radius-lg`, `--font-mono`).
- [ ] `test('no raw hex color literals remain outside tokens.css')` —
      рекурсивный обход `ui/src/**/*.vue` и `ui/src/**/*.js` (кроме самого
      `tokens.css`), regex `/#[0-9a-fA-F]{3,6}\b/`, ожидание — пустой список
      совпадений. Падает сейчас (99 вхождений в 16 файлах) — это и есть
      падающий тест, который чинит вся стадия.
- [ ] Прогнать перед правками, чтобы зафиксировать текущее число
      совпадений (не для ассерта — для ручной сверки, что регрессии по
      количеству не осталось).

### Implementation

- [ ] Создать `ui/src/styles/tokens.css` с полным набором переменных из
      спека [S3] (значения — как в текущих hex-литералах; для
      `--color-text-muted`/`--color-text-faint` — консолидация
      `#555/#666` → muted, `#888/#999/#aaa/#ccc` → faint, см. [S2]).
- [ ] Импортировать `tokens.css` в `ui/src/main.js` перед `mount()`.
- [ ] `App.vue` (`<style>`, строки 46-78) — заменить каждый hex-литерал на
      соответствующий `var(--...)`.
- [ ] Пройтись по всем 16 файлам с hex-литералами (`Actions.vue`,
      `ApiKeys.vue`, `AuditLog.vue`, `Connectors.vue`, `Generate.vue`,
      `HistoryPanel.vue`, `JobDetail.vue`, `Jobs.vue`, `Login.vue`,
      `Prompts.vue`, `Settings.vue`, `Status.vue`, `Tools.vue`,
      `Toast.vue`, `Users.vue`, `Workflows.vue`) — заменить inline
      `style="color:#..."` / `background:#..."` на `var(--...)`.
- [ ] Прогнать regex-проверку из теста вручную (`grep -rE
      "#[0-9a-fA-F]{3,6}" ui/src`) — подтвердить 0 совпадений вне
      `tokens.css`.

---

## Часть B — nav-группировка

### Тесты первыми (`ui/tests/nav.spec.js`, расширение существующего)

- [ ] `it('keeps the secondary group collapsed by default')` — свежий
      `localStorage` (очистить в `beforeEach`), монтирование `App` для
      `admin`: `wrapper.find('[data-test="nav-more-panel"]').isVisible()`
      → `false`. Существующие проверки `nav.text()` (тест "shows admin
      every section") не меняются — секция остаётся в DOM (`v-show`, не
      `v-if`), просто скрыта стилем, `textContent` её всё равно видит.
- [ ] `it('opens the secondary group on toggle click')` — клик по
      `[data-test="nav-more-toggle"]`, панель `isVisible() === true`,
      `localStorage.getItem('soar.nav.moreOpen') === '1'`.
- [ ] `it('restores the open state from localStorage on mount')` —
      `localStorage.setItem('soar.nav.moreOpen', '1')` до монтирования →
      панель видима сразу, без клика.
- [ ] `it('closes on a click outside the nav')` — открыть, затем
      `document.body.click()` (или клик по элементу вне `nav`) → панель
      скрыта.

### Implementation (`App.vue`)

- [ ] Разбить `<nav>` на primary-ссылки (как сейчас: Status, Workflows,
      Jobs, Actions, Connectors) и secondary — обернуть Tools, Prompts,
      Generate, Settings, Users, API Keys, Audit Log в
      `<div class="nav-more-panel" v-show="moreOpen" data-test="nav-more-panel">`
      с теми же `v-if="can(...)"`, что сейчас.
- [ ] Toggle-кнопка `⚙ More` (`data-test="nav-more-toggle"`) — `@click.stop
      = "toggleMore"`.
- [ ] `moreOpen` — `ref(localStorage.getItem('soar.nav.moreOpen') === '1')`;
      `toggleMore` пишет новое значение в `localStorage`.
- [ ] Обработчик клика вне (`document` listener в `onMounted`/убрать в
      `onUnmounted`) закрывает панель, если открыт клик снаружи `.nav-more`.
- [ ] CSS: `.nav-more { position: relative; }`, `.nav-more-panel {
      position: absolute; top: 100%; right: 0; background:
      var(--color-surface-dark); display: flex; flex-direction: column; }`
      (добавляется в Часть A токены, если ещё не создан этот файл к
      моменту работы над Частью B — порядок не жёсткий, но токены нужны).

---

## Часть C — `RowMenu.vue`

### Тесты первыми (`ui/tests/row-menu.spec.js`, новый файл)

- [ ] `it('renders closed by default')` — `wrapper.find('.row-menu-panel').exists()`
      → `false`.
- [ ] `it('opens on toggle click and shows slot content')` — слот с
      `<button>Delete</button>`, после клика на `.row-menu-toggle` —
      кнопка видна.
- [ ] `it('closes after clicking an item inside the slot')` — клик по
      кнопке в слоте → панель закрывается (`.row-menu-panel` снова
      `exists() === false`).
- [ ] `it('closes on outside click')`.

### Implementation

- [ ] `ui/src/components/RowMenu.vue` — toggle-кнопка «⋮» + `v-if`-панель
      со слотом, закрытие по клику вне и по клику на пункт внутри слота
      (см. разметку в спеке [S5]).
- [ ] `.row-menu`, `.row-menu-toggle`, `.row-menu-panel`,
      `.row-menu-item-danger` — новые классы в `App.vue` `<style>`, на
      токенах из Части A.
- [ ] `Workflows.vue` (строки 42-53) — видимая кнопка `Edit`/`View`
      остаётся вне меню; `Enable`/`Disable`, `Run`, `Jobs`, `Audit`,
      `Delete` переносятся внутрь `<RowMenu>` без изменения `v-if`/`@click`.
- [ ] `Actions.vue` (строки 31-33) — `Audit`/`Delete` внутрь `<RowMenu>`.
- [ ] `Connectors.vue` (строки 32-38) — `Edit`/`Setup` остаются видимыми
      кнопками; `Audit`/`Delete` — внутрь `<RowMenu>`.
- [ ] Существующие smoke/functional тесты `Workflows`/`Actions`/`Connectors`
      (если есть, проверить `ui/tests/`) — прогнать, поправить селекторы,
      если они находили кнопки по прямому CSS-пути в таблице, а не по
      тексту/`data-test`.

---

## Часть D — toolbar редактора

### Тесты первыми

- [ ] Расширить существующие smoke-тесты редакторов (или добавить в
      `ui/tests/`, если их нет для `Workflows`/`Actions`/`Connectors`) —
      `wrapper.find('.editor-toolbar').exists()` после открытия
      редактора, содержит кнопки Save/Close/вкладки, которые сейчас
      проверяются по тексту — тест не должен ломаться при перестановке
      разметки `<h2>`/toolbar.

### Implementation

- [ ] `Workflows.vue`, `Actions.vue`, `Connectors.vue` (обе панели: код и
      конфиг) — вынести строку с вкладками/Save/Close в
      `<div class="editor-toolbar">`, `<h2>` — отдельной строкой над ней.
      Логика кнопок (`v-if`, `@click`, `:class`) не меняется, меняется
      только обёртка/расположение.
- [ ] `.editor-toolbar` — новый класс в `App.vue` `<style>`: `position:
      sticky; top: 0; background: var(--color-surface); z-index: 1;
      padding: var(--space-2) 0; border-bottom: 1px solid
      var(--color-border-subtle);`.

---

## Часть E — `Loading.vue` и `.empty`

### Тесты первыми (`ui/tests/loading.spec.js`, новый файл)

- [ ] `it('renders a spinner and default label')`.
- [ ] `it('renders a custom label when provided')`.
- [ ] Обновить/расширить smoke-тесты вьюх, где сейчас ищут текст
      `'Loading...'`, чтобы вместо этого искали компонент/класс
      `.loading-spinner` — иначе они станут ложно-падающими после замены
      разметки.

### Implementation

- [ ] `ui/src/components/Loading.vue` — спиннер + `label` prop (дефолт
      `'Loading…'`), разметка и CSS-анимация из спека [S7].
- [ ] Заменить `<div v-if="loading" class="loading">Loading...</div>` на
      `<Loading v-if="loading" />` во всех вьюхах, где встречается паттерн
      (`Workflows.vue`, `Actions.vue`, `Connectors.vue`, `Jobs.vue`,
      `Status.vue`, `AuditLog.vue`, `Tools.vue`, `Prompts.vue`,
      `Generate.vue`, `Settings.vue`, `ApiKeys.vue`, `Users.vue`,
      `JobDetail.vue` — сверить фактическое присутствие паттерна перед
      правкой, список из спека мог не учесть все вхождения).
- [ ] Добавить класс `.empty` в `App.vue` `<style>` (внешний вид как у
      старого `.loading`: `color: var(--color-text-faint); font-style:
      italic;`), заменить вторичное использование `.loading` для пустых
      списков (`Actions.vue:36`, `Jobs.vue:49` и другие найденные тем же
      grep'ом) на `.empty`.
- [ ] `.loading` в `App.vue` `<style>` остаётся только за
      `.loading-spinner`/`Loading.vue` — если старый класс `.loading`
      после правки больше нигде не используется как отдельная сущность,
      переименовать его роль в CSS явно (не оставлять две семантики под
      одним именем).

---

## Verification

- [ ] `cd ui && npm test` — все новые и существующие тесты зелёные
- [ ] `grep -rE "#[0-9a-fA-F]{3,6}" ui/src` — ничего вне `ui/src/styles/tokens.css`
- [ ] `cd ui && npm run dev` — ручной чеклист из спека [S8]:
      1. Визуальное сравнение до/после (Стадия A не должна менять вид)
      2. Окно ≤900px — nav не переносится, "More" схлопнут
      3. Таблица Workflows — одна кнопка + «⋮», Delete в меню визуально
         отличается
      4. Длинный код в редакторе, скролл — toolbar остаётся на виду
      5. Пустой список показывает `.empty`, загрузка — спиннер
- [ ] Ни одной правки в `orchestrator/`/`soar/`
- [ ] Написать отчёт `docs/compose/reports/ui-redesign-structural.md`
      (Часть 3 целиком: A-E), отметить в `docs/concepts/UI-REDESIGN.md`
      чеклист "Часть 3" как выполненный
