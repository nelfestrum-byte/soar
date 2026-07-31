# UI-редизайн: структурные стадии (Часть 3)

> Реализация Части 3 [`UI-REDESIGN.md`](../../concepts/UI-REDESIGN.md) —
> единственная часть концепта, не заблокированная на результате Google
> Stitch (Часть 4). Часть 4 выполняется пользователем параллельно во
> внешнем инструменте; Часть 5 (внедрение стиля) начнётся отдельным
> спеком, когда результат Stitch будет готов.
>
> Значения токенов в этом спеке **совпадают с текущими** — это
> тонкая настройка точки изменения, не смена палитры. Новая палитра —
> предмет Части 5.1, отдельного спека.

## [S1] Problem

Ссылки на разделы `UI-REDESIGN.md`:

- **V1** — цвета захардкожены как hex-литералы в `App.vue:46-78` и в
  inline `style="..."` по вьюхам (99 вхождений hex-цвета в 16 файлах,
  проверено grep'ом). Нет `:root` с CSS-переменными — поменять палитру
  сегодня означает править каждый файл вручную.
- **V2** — `App.vue:3-16`: 12 пунктов навигации в один `<nav>` без
  иерархии; для `admin` строка не помещается на узких окнах.
- **V3** — до 6 кнопок в строке таблицы (`Workflows.vue:42-53`): primary-
  действие (Edit/Run) неотличимо по весу от Delete.
- **V4** (Monaco) — не входит в этот спек, отдельная стадия Части 5.4.
- **Toolbar редактора** — `<h2>` и вкладки/Save/Close в одной строке
  (`Workflows.vue:88-99`, `Actions.vue:39-50`, `Connectors.vue:44-54,
  83-93`) — тесно, не sticky при длинном содержимом.
- **Loading/empty** — `class="loading"` переиспользуется для двух разных
  смыслов: "идёт загрузка" (`Jobs.vue:18`) и "список пуст"
  (`Actions.vue:36`, `Jobs.vue:49`) — визуально не различить.

## [S2] Solution — форма и границы

Только `ui/`, без правок бэкенда. Пять стадий, каждая независима и
проверяется отдельно (порядок — от простого к сложному, не обязателен).

| Стадия | Закрывает | Суть |
|--------|-----------|------|
| A | V1 | `tokens.css`, глобальный CSS и inline-стили переведены на `var()` |
| B | V2 | Nav: primary-группа + collapsible "⚙ More" |
| C | V3 | `RowMenu.vue` — оverflow-меню «⋮» в таблицах Workflows/Actions/Connectors |
| D | toolbar | Toolbar редактора — отдельная sticky-полоса |
| E | loading/empty | `Loading.vue` + класс `.empty` вместо переиспользования `.loading` |

**Явные границы:**

- Никаких новых значений цвета — только перенос текущих hex-литералов в
  переменные. Одно исключение с сохранением смысла: несколько близких
  оттенков серого (`#555/#666/#888/#999/#aaa/#ccc`), используемых как
  синонимы "приглушённый текст" в разных вьюхах без системы, схлопываются
  в два токена — `--color-text-muted` и `--color-text-faint` (см. Стадию
  A). Это единственное место, где значение токена не совпадает
  побайтово с одним из исходных литералов — визуальная разница на глаз
  не различима (соседние оттенки серого), а восстановленная точка
  изменения важнее point-perfect копии текущего дрейфа.
- Monaco, диффы бок-о-бок, тема (свет/тьма) — не в этом спеке (Часть 2 и
  Часть 5 соответственно).
- Компонентные библиотеки (Vuetify и т.п.) не вводятся — только новые
  generic-компоненты (`RowMenu.vue`, `Loading.vue`) поверх существующих
  классов (`.btn`, `.card`, `.badge`).
- `Jobs.vue` не трогается в Стадии C: у него максимум 3 действия в
  строке (Log/Audit/Cancel), сама строка кликабельна и открывает деталь
  — ровно то состояние, к которому стремится V3, уже есть.

## [S3] Стадия A — `tokens.css`

Новый файл `ui/src/styles/tokens.css`, импортируется из `main.js` перед
`App.vue`. Полный набор переменных — по инвентаризации всех различимых
hex-значений в `ui/src` (grep, 29 уникальных цветов без учёта HTML-
сущностей `&#10003;`/`&#10007;`/`&#9202;`, которые не цвета):

```css
:root {
  /* поверхности */
  --color-surface: #fff;
  --color-surface-alt: #fafafa;      /* th, hover-строки, detail-row фон */
  --color-surface-dark: #1a1a2e;     /* nav, <pre> (лог) */
  --color-surface-hover: #f5f7fa;    /* .job-row:hover */

  /* текст */
  --color-text: #333;
  --color-text-muted: #666;          /* заменяет #666/#555 */
  --color-text-faint: #999;          /* заменяет #999/#888/#aaa/#ccc */
  --color-text-on-dark: #a5d6a7;     /* текст в <pre> */

  /* границы */
  --color-border: #ddd;
  --color-border-subtle: #eee;

  /* акцент/действия */
  --color-accent: #4fc3f7;
  --color-accent-fg: #000;
  --color-danger: #ef5350;
  --color-success: #66bb6a;
  --color-result-ok: #2e7d32;
  --color-result-fail: #c62828;

  /* статус-бейджи (6 состояний джобы) — фон/текст парой */
  --status-pending-bg: #fff3e0;  --status-pending-fg: #e65100;
  --status-running-bg: #e3f2fd;  --status-running-fg: #1565c0;
  --status-completed-bg: #e8f5e9; --status-completed-fg: #2e7d32;
  --status-failed-bg: #ffebee;    --status-failed-fg: #c62828;
  --status-cancelled-bg: #f3e5f5; --status-cancelled-fg: #7b1fa2;
  --status-timeout-bg: #fce4ec;   --status-timeout-fg: #ad1457;

  /* spacing / прочее */
  --space-1: 4px; --space-2: 8px; --space-3: 12px;
  --space-4: 16px; --space-5: 24px; --space-6: 32px;
  --radius: 4px;
  --radius-lg: 8px;
  --font-mono: monospace;
}
```

Правки:

- `App.vue`'s `<style>` (строки 46-78) — все hex-литералы заменяются на
  `var(--...)`. Значения не меняются.
- Inline `style="color:#666"` / `background:#fafafa"` и т.п. по всем 16
  файлам (`Workflows.vue`, `Actions.vue`, `Connectors.vue`, `Jobs.vue`,
  `Status.vue`, `AuditLog.vue`, `Tools.vue`, `Prompts.vue`, `Generate.vue`,
  `Settings.vue`, `ApiKeys.vue`, `Users.vue`, `JobDetail.vue`, `Login.vue`,
  `HistoryPanel.vue`, `Toast.vue`) — заменяются на `var(--...)` по
  таблице выше.
- **Проверка полноты**: после правки `grep -rE "#[0-9a-fA-F]{3,6}" ui/src`
  не должен находить ничего, кроме `tokens.css` самого.

## [S4] Стадия B — nav-группировка

`App.vue`:

- Primary-группа (всегда видна): Status, Workflows, Jobs, Actions,
  Connectors — как сейчас, без изменений в разметке.
- Secondary-группа под toggle `⚙ More`: Tools, Prompts, Generate
  (`can(auth.role,'connector.manage')`), Settings
  (`can(auth.role,'transfer')`), Users/API Keys
  (`can(auth.role,'auth.admin')`), Audit Log (`can(auth.role,'audit.read')`)
  — те же `v-if`, что сейчас, без изменения прав.
- Toggle — кнопка в `<nav>`, открывает выпадающую панель (`position:
  absolute`) со secondary-ссылками в столбец; закрывается по клику вне
  панели или по переходу на ссылку внутри неё (обычное поведение
  dropdown).
- **Персистентность**: состояние открыт/закрыт при **первой загрузке
  страницы** читается из `localStorage['soar.nav.moreOpen']` — если
  `'1'`, панель рендерится открытой сразу, без клика. При каждом
  toggle — запись обратно в `localStorage`. Это единственная память
  между перезагрузками; в остальном поведение — обычный dropdown.

## [S5] Стадия C — `RowMenu.vue`

Новый `ui/src/components/RowMenu.vue` — toggle-кнопка «⋮» + выпадающая
панель со слотом:

```vue
<template>
  <span class="row-menu">
    <button class="btn row-menu-toggle" @click.stop="open = !open">⋮</button>
    <div v-if="open" class="row-menu-panel" @click="open = false">
      <slot />
    </div>
  </span>
</template>
```

Закрытие по клику вне (`@click` на `document`, добавляется/убирается в
`onMounted`/`onUnmounted`). Слот получает существующие
кнопки/`router-link` как есть — переносится разметка, не переписывается
логика (`v-if`/`can()`/`@click` остаются один в один).

Применение:

- **`Workflows.vue`** (строки 42-53): видимая кнопка — `Edit`/`View`
  (было и остаётся). В `RowMenu`: `Enable`/`Disable`, `Run` (если
  `manual` и `canRun`), `Jobs`, `Audit`, `Delete`.
- **`Actions.vue`** (строки 31-33): видимого действия-кнопки нет (клик
  по имени — уже открытие). В `RowMenu`: `Audit`, `Delete`. Оставляю
  этот перенос ради единообразия паттерна со списком остальных сущностей
  (тот же приём, что в V3), хотя действий всего два.
- **`Connectors.vue`** (строки 32-38): видимые кнопки — `Edit` (код) и
  `Setup` (конфиг), обе одинаково часто используемые primary-действия —
  остаются видимыми. В `RowMenu`: `Audit`, `Delete`.

`.row-menu-panel` — `position: absolute`, `background:
var(--color-surface)`, `border: 1px solid var(--color-border)`, пункты —
блочные ссылки/кнопки на всю ширину панели (не `.btn` строкой). Delete
внутри панели помечается `.row-menu-item-danger`
(`color: var(--color-danger)`), визуально отделён от остальных пунктов —
закрывает жалобу V3 "разрушительное действие в общем ряду".

## [S6] Стадия D — toolbar редактора

В `Workflows.vue`, `Actions.vue`, `Connectors.vue` (обе панели —
код и конфиг) карточка редактора сейчас — один flex-ряд `<h2>` +
вкладки/Save/Close. Меняется на:

```
<h2>{{ name }}</h2>
<div class="editor-toolbar">
  <!-- вкладки слева, Save/Close справа — как сейчас, без изменения логики -->
</div>
<!-- содержимое вкладки -->
```

`.editor-toolbar` — новый класс в глобальном `<style>` `App.vue`:
`position: sticky; top: 0; background: var(--color-surface); z-index: 1;
padding: var(--space-2) 0; border-bottom: 1px solid
var(--color-border-subtle);` — при длинном `<textarea>`/содержимом
вкладки полоса с кнопками остаётся на виду при скролле карточки.
Разметка `<h2>` выносится отдельной строкой над полосой (сейчас — в
одном flex-ряду с кнопками, из-за чего тесно при длинных именах).

## [S7] Стадия E — `Loading.vue` и `.empty`

Новый `ui/src/components/Loading.vue`:

```vue
<template>
  <div class="loading-spinner"><span class="spinner"></span> {{ label }}</div>
</template>
<script setup>
defineProps({ label: { type: String, default: 'Loading…' } })
</script>
```

`.spinner` — CSS-анимация (border-spin), без библиотек. Заменяет во всех
вьюхах `<div v-if="loading" class="loading">Loading...</div>`.

Отдельный класс `.empty` (в `App.vue`, тот же вид текста, что сейчас
даёт `.loading`, но по смыслу — не идёт загрузка, а данных нет) заменяет
вторичное использование `.loading` для пустых списков: `Actions.vue:36`
("No actions yet"), `Jobs.vue:49` ("No jobs found") и аналогичные.
`.loading` (класс) остаётся только за `Loading.vue`.

## [S8] Testing Strategy

Юнит (vitest, `ui/tests/`):

- `tokens.spec.js` — читает `App.vue` и все вьюхи, проверяет отсутствие
  hex-литералов (`#[0-9a-fA-F]{3,6}`) вне `tokens.css` — регрессионный
  тест на "не откатились на литералы".
- `row-menu.spec.js` — монтирование `RowMenu.vue`: закрыт по умолчанию,
  открывается по клику на toggle, закрывается по клику вне компонента и
  по клику на пункт внутри слота.
- `nav.spec.js` (уже существует, `ui/tests/nav.spec.js`) — дополняется
  проверкой: secondary-ссылки не видны без явного открытия "More" (если
  `localStorage` пуст), видны сразу при `localStorage['soar.nav.moreOpen']
  === '1'`.
- Smoke-монтирование вьюх с `RowMenu`/`Loading` (уже покрыто существующими
  smoke-тестами `Workflows`/`Actions`/`Connectors` — не падают на новых
  импортах).

Ручной чеклист (в отчёт):

1. Каждая вьюха визуально не изменилась в цвете/интервалах (сравнение
   до/после в дев-сервере) — Стадия A не меняет вид, только источник
   значений.
2. Узкое окно (≤900px) — nav не переносится на вторую строку благодаря
   collapsed "More".
3. Таблица Workflows — в строке одна видимая кнопка + «⋮»; открыть меню,
   убедиться что Delete визуально отличается (цвет) от остальных пунктов.
4. Открыть редактор кода с длинным содержимым, проскроллить — toolbar
   (вкладки/Save/Close) остаётся на виду.
5. Список без данных (например, `Actions.vue` без ни одного action)
   показывает `.empty`, а не спиннер; загрузка страницы на секунду
   показывает спиннер `Loading.vue`, не текст.

## [S9] Success Criteria

- [ ] `grep -rE "#[0-9a-fA-F]{3,6}" ui/src` не находит ничего вне
      `ui/src/styles/tokens.css`
- [ ] Nav помещается в одну строку на 900px за счёт collapsed "More";
      состояние open/closed переживает перезагрузку страницы
- [ ] В строках таблиц Workflows/Actions/Connectors не более одного/двух
      явных кнопок + «⋮»; Delete в меню визуально отличается от прочих
      пунктов
- [ ] Toolbar редактора sticky при скролле длинного содержимого
- [ ] `.loading` используется только для реальной загрузки; пустые списки
      используют `.empty`
- [ ] `npm test` зелёный; ни одной правки в `orchestrator/`/`soar/`
- [ ] Визуально приложение не изменилось (Стадия A — перенос значений,
      не новая палитра)
