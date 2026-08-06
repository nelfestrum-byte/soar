# UI-REDESIGN.md — визуальный стиль и удобство редактирования

> Продолжение [`docs/compose/specs/2026-07-29-ui-control-visibility-design.md`](../compose/specs/2026-07-29-ui-control-visibility-design.md),
> которая закрывала видимость логов/аудита/истории, но редизайн (тема,
> layout, компонентная библиотека) в неё сознательно не входил — см. [S2]
> того спека: «Из скоупа исключены: редизайн... Стиль остаётся текущим».
> Этот документ — то самое исключённое, теперь как отдельная задача.
>
> Верхнеуровневая карта, не спек. Каждая стадия перед реализацией получает
> обычный спек/план/отчёт по правилам `CLAUDE.md` — этот файл фиксирует
> объём и порядок, не заменяет их.
>
> **Статус: Часть 3 и Часть 4 выполнены** (см. чеклист в конце файла и
> `docs/compose/reports/ui-redesign-structural.md`). Часть 5 (внедрение
> палитры Stitch) не начата — отдельный спек/план на момент решения по ней.

## Принцип

Визуальный стиль — не то, что можно решить внутренним обсуждением: нет
дизайнера в проекте, оценивать «красиво или нет» не на чем. Поэтому вместо
того, чтобы придумывать палитру и типографику самим, объём разбит на
«структурные» стадии (1–3 — то, что можно решить инженерно: какой виджет
редактора, какая структура навигации, какие токены нужны технически) и
«визуальные» (4–5 — стиль приходит извне, из Google Stitch, а сюда
переносится уже готовым). Структурные стадии не блокируются на результате
Stitch и могут делаться уже сейчас; 5-я стадия блокируется на 4-й.

## Часть 1 — Анализ текущего UI

Ревизия `ui/src/` (App.vue, 15 views, HistoryPanel/Toast). Без правок
бэкенда — как и в предыдущем UI-спеке, это не нужно.

### V1. Нет дизайн-токенов — только inline-стили и глобальные классы

`App.vue:46-78` — один блок CSS на всё приложение: цвета захардкожены как
hex-литералы (`#4fc3f7`, `#1a1a2e`, `#66bb6a`...) прямо в правилах, без
единой точки изменения. Поверх этого в каждой вьюхе — inline `style="..."`
на конкретных элементах (`Workflows.vue` — 30+ вхождений: `font-size:11px`,
`gap:8px`, цвета через `color:#666`). Изменить палитру сегодня значит
пройти по всем файлам и заменить литералы вручную — ни `:root` с
CSS-переменными, ни общего файла токенов нет. Это первое, что нужно
починить технически, независимо от того, какой стиль придёт от Stitch —
иначе применить его результат тоже придётся вручную по всем файлам.

### V2. Плоский nav — 12 пунктов в один ряд без группировки

`App.vue:3-23` — все ссылки в один `<nav>` без иерархии: Status, Workflows,
Jobs, Actions, Connectors, Tools, Prompts, Generate, Settings, Users, API
Keys, Audit Log. Для `admin` это уже 12 пунктов в одну строку — на узких
окнах переносится некрасиво, а по мере роста функциональности (Prompts и
Generate добавились недавно) будет только хуже. Разделения на «часто
нужное» (Status/Workflows/Jobs) и «административное» (Users/API
Keys/Settings/Audit Log) нет — они визуально равноправны.

### V3. До 6 кнопок в строке таблицы

`Workflows.vue:42-53` — в одной строке таблицы: Disable/Enable, Edit, Run,
Jobs (router-link как кнопка), Audit (router-link как кнопка), Delete — до
шести элементов, каждый с ручным `style="font-size:11px"`. Та же картина в
`Actions.vue`, `Connectors.vue`. Primary-действие (Edit/Run) неотличимо по
весу от Delete — разрушительное действие в общем ряду с навигационными
ссылками.

### V4. Редактор кода — обычный `<textarea>`, diff — текст с `+`/`-`

Все редакторы (workflow/action/connector код, connector config, user
prompt) — один и тот же паттерн: `<textarea>` без подсветки синтаксиса,
без номеров строк, без автодополнения скобок (`Workflows.vue:101`,
идентично в `Actions.vue`/`Connectors.vue`/`Prompts.vue`). Diff в
`HistoryPanel` (заведён спеком 2026-07-29, [S5]) выводит unified diff как
текст с раскраской по первому символу строки — не сравнение бок-о-бок.
Для Python-кода это ощутимо хуже, чем то, к чему привык любой, кто хоть
раз открывал VS Code.

### V5. Несогласованные состояния — частично уже чинится

`error.value` / `saveResult` / `alert()` — три способа показать ошибку
(зафиксировано в самом 2026-07-29 спеке, [S3], как задача стадии 0). Не
дублирую здесь как отдельную проблему — но результат той стадии (единый
`Toast`) должен лечь в новую визуальную систему, а не остаться отдельным
островком со своими стилями.

### V6. Тема — не решение, а совпадение

Тёмный `<nav>` (`#1a1a2e`) и тёмный `<pre>` для логов — но весь остальной
контент светлый (`.card` — `background:#fff`). Это не «тёмная тема с
акцентами», а два независимых решения, которые оказались рядом. Ни
переключателя, ни последовательной тёмной/светлой палитры нет.

## Часть 2 — Целевой UX редактирования: Monaco, не полноценный VS Code Web

Из формулировки задачи — «что-то типа VSCode Web». Важно сузить: нужен
редактор с подсветкой синтаксиса, номерами строк и normal diff-view, а не
полноценная IDE (file tree, терминал, extensions). У сущностей SOAR нет
множественных файлов на редактирование — воркфлоу/экшен/коннектор это один
файл кода (+ у коннектора отдельно один файл конфига), workspace с деревом
файлов моделировать не на чем и незачем.

**Решение: [Monaco Editor](https://microsoft.github.io/monaco-editor/)** —
тот же движок редактора, что в самом VS Code, как отдельная npm-зависимость
(`monaco-editor` + обёртка `@guolao/vue-monaco-editor` или аналог для Vue
3), без остальной IDE вокруг.

- **Синтаксис**: `python` для code-полей, `json` для конфигов/payload'ов —
  Monaco умеет оба из коробки.
- **Diff-view для `HistoryPanel`** ([S5] 2026-07-29-спека): Monaco даёт
  `DiffEditor` — сравнение бок-о-бок с подсветкой готовое, взамен
  самодельного текстового +/-. Прямая замена в том же компоненте, API не
  меняется (те же данные с `.../diff?a=&b=`).
- **Права доступа** — та же модель, что уже есть: `readOnly: !canWrite`
  на инстансе редактора вместо `:readonly` на `<textarea>`. `permissions.js`
  не меняется.
- **Вкладки внутри карточки** — уже существующий паттерн (Code/History в
  `Workflows.vue:92-93`) сохраняется; для коннектора добавляется вкладка
  Config рядом с Code, а не отдельный экран.
- **Bundle**: Monaco — это несколько мегабайт. Грузить только по
  `dynamic import()` в момент открытия редактора (Vite поддерживает
  code-splitting «из коробки»), не в основной бандл — иначе весь UI
  тяжелеет ради вьюх, которые не все роли даже видят (`viewer` код не
  редактирует вовсе).
- **Явно не берём**: `code-server`/полноценный VS Code Web как iframe или
  отдельный сервис — это отдельный процесс, доступ к файловой системе,
  свой auth-периметр; несоразмерно задаче «отредактировать один файл
  сущности через API, который уже есть».

## Часть 3 — Реформат расположения элементов

Технические предпосылки под визуальный стиль — делаются независимо от
результата Stitch, но так, чтобы стиль лёг на готовую структуру, а не
поверх текущего inline-хаоса.

- **Design tokens**: `ui/src/styles/tokens.css` — `:root { --color-bg,
  --color-surface, --color-accent, --color-danger, --space-1..6,
  --radius, --font-mono, ... }`. Все hex-литералы из `App.vue` и
  inline-стилей вьюх переезжают на переменные. Это ровно то место, куда
  ляжет результат Stitch на стадии 5 — без него внедрение стиля означает
  правку каждого файла вручную.
- **Nav**: группировка на «основное» (Status/Workflows/Jobs/Actions/
  Connectors) — всегда видно, и «административное» (Tools/Prompts/
  Generate/Settings/Users/API Keys/Audit Log) — под collapsible
  меню/иконкой (например «⚙ More»), с учётом `can()` как сейчас. Состояние
  (открыто/закрыто) — в `localStorage`, не в сторе.
- **Row actions**: primary-действие (Edit/Run) остаётся видимой кнопкой;
  остальное (Jobs/Audit/Delete/Enable-Disable) — в выпадающее меню «⋮» на
  строке. Тот же приём, что в V3, закрывает главную визуальную жалобу —
  «слишком много кнопок» — ещё до того, как придёт новая палитра.
- **Карточки редактора**: toolbar (Code/History/Config-вкладки + Save/
  Close) выносится в отдельную полосу с sticky-позиционированием при
  длинном содержимом — сейчас кнопки в одну строку с `<h2>` тесно.
- Loading/empty states — вместо текста `Loading...` / `—` единый
  компонент-заглушка (скелетон или спиннер), переиспользуемый как `Toast`.

Это даёт «современные UI-трюки» из пункта 3 задачи независимо от того, что
скажет Stitch про цвет — collapsible-навигация и меню действий это вопрос
структуры, не палитры.

## Часть 4 — Промпт для Google Stitch

Экспортируемый результат нужен не как картинка, а как переносимая система:
палитра, типографика, spacing-шкала, состояния компонентов — то, что можно
превратить в файл из Части 3 (`tokens.css`). Промпт составлен так, чтобы
явно это запросить, плюс описывает все типы экранов, которые реально есть
в приложении (не абстрактный «admin dashboard»).

Вставлять в Stitch как есть (инструмент англоязычный, промпт — на
английском для предсказуемости; кириллица в нём тоже воспринимается, но
проверено хуже):

```
Design a visual style system for an internal security-operations (SOAR)
web console used by security analysts and admins to manage automated
investigation workflows, connectors, and jobs. This is an operator tool,
not a marketing site — prioritize information density, scanability, and
low visual noise over decoration. Users often work under incident-response
time pressure and need to spot status (success/failure/running) at a
glance.

Generate a cohesive design system, not a single mockup, covering these
screen types:
1. A status dashboard with stat tiles and a scheduler timeline.
2. Dense data tables with sortable columns, expandable detail rows, and a
   per-row overflow ("⋮") menu for secondary actions.
3. A code editor panel (VS Code-like: monospace, line numbers, syntax
   highlighting) shown inside a card next to metadata fields, with tabs
   for switching between "Code" / "Config" / "History".
4. A side-by-side diff view (old vs new code revision).
5. A job detail page with a status badge, a collapsible JSON payload
   block, and a scrolling log/traceback panel in a terminal-like style.
6. Simple CRUD forms (users, API keys) with role-select dropdowns.
7. A left sidebar navigation with a primary group (always visible) and a
   secondary "More" group that collapses.

Requirements:
- Dark theme as the primary mode (operator/SOC tool convention); also
  provide a light-mode variant of the same tokens.
- A status/badge color set for exactly six states: pending, running,
  completed, failed, cancelled, timeout — each needs a distinct,
  colorblind-safe color.
- An accent color family (current app uses a cyan/blue accent, open to
  refreshing it) plus a danger/destructive color for delete actions,
  clearly distinct from the failed-status color.
- Typography: one sans-serif for UI text, one monospace for code/logs/IDs,
  with a defined type scale (sizes for h1/h2/body/small/code).
- Spacing scale (e.g. 4/8/12/16/24/32px) and a consistent border-radius
  value for cards/buttons/inputs.
- Component states: default/hover/active/disabled/focus-visible for
  buttons and table rows.

Deliverable: a design system I can translate into CSS custom properties
(colors, spacing, radius, font stacks, font sizes) plus example
screens for the 7 types above styled with that system. This will be
implemented in a plain Vue 3 app — no dependency on a specific component
library, so keep components generic (buttons, badges, cards, tables,
tabs, dropdown menus) rather than tied to a particular design framework.
```

Результат из Stitch (палитра/типографика/спейсинг + референс-экраны) —
вход для стадии 5, не финальный артефакт сам по себе.

## Часть 5 — Внедрение стиля (после результата Stitch)

Блокируется на Части 4. Порядок — от токенов наружу, каждая стадия
самостоятельно проверяема, как в 2026-07-29-спеке:

1. **Токены** — перенести палитру/шкалы из Stitch в `tokens.css` (Часть 3).
   Ничего в разметке ещё не меняется.
2. **Глобальные классы** — `.card`/`.btn`/`.badge`/таблицы/`pre` в
   `App.vue` переключаются на переменные вместо литералов. Это уже
   перекрашивает ~80% приложения, потому что все вьюхи их переиспользуют.
3. **Nav + row actions** — структурные правки Части 3 (collapsible-меню,
   overflow «⋮») реализуются одновременно с применением нового стиля к
   ним, чтобы не красить дважды.
4. **Monaco-редакторы** — замена `<textarea>` (Часть 2), последней, потому
   что это отдельная зависимость и наибольший по объёму риск (bundle,
   права доступа, поведение на мобильных — если оно вообще нужно).

Каждая стадия — свой спек в `docs/compose/specs/`, свой план в
`docs/compose/plans/`, свой отчёт по завершении — по обязательному порядку
из `CLAUDE.md`. Этот файл переходит в статус «реализовано» только когда
все стадии закрыты и написаны соответствующие спек/план/отчёт.

## Часть 6 — Границы

Не входит в этот концепт:

- Смена фреймворка (Vue 3 остаётся) или подключение тяжёлой компонентной
  библиотеки (Vuetify/Element Plus и т.п.) — токены и generic-компоненты
  своей разработки, как и указано в промпте Stitch.
- i18n — вне скоупа, как и в 2026-07-29-спеке.
- Правки бэкенда — ни одного эндпоинта, ни одной модели.
- Полноценный VS Code Web / `code-server` — см. Часть 2, сознательно не
  берём.
- Мобильная адаптация как отдельная цель — если ляжет естественно из
  responsive-токенов, хорошо, но не отдельная стадия.

## Открытые вопросы (к пользователю, до старта стадии 5)

- Тема: только тёмная, или нужен переключатель тёмная/светлая? (влияет на
  объём промпта и токенов — в промпте Части 4 уже заложен запрос обеих
  палитр на случай переключателя)
- Готовность принять рост бандла из-за Monaco (даже при lazy-load, это
  новая зависимость с известным весом) — альтернатива полегче (например
  CodeMirror 6) возможна, если размер критичен, но диалог сейчас не
  указывал на этот приоритет.

## Чеклист стадий

- [x] Часть 3 (nav/row actions/tokens-каркас) — реализовано,
      `docs/compose/reports/ui-redesign-structural.md`
- [x] Часть 4 — промпт передан в Google Stitch, результат сохранён в
      `docs/concepts/stitch_sentinel_soar_design_system/`
- [x] Часть 5.1 — токены из результата Stitch,
      `docs/compose/reports/ui-redesign-stitch-tokens.md`
- [x] Часть 5.2 — глобальные классы на токенах (побочный эффект Части 3,
      где `.card`/`.btn`/`.badge`/таблицы/`pre` уже были переведены на
      `var(--...)` — Часть 5.1 просто поменяла значения переменных)
- [ ] Часть 5.3 — nav/row actions в новом стиле
- [x] Часть 5.4 (Monaco вместо `<textarea>`) — реализовано 2026-08-06,
      `docs/compose/reports/monaco-editor.md`; diff-editor в `HistoryPanel`
      сознательно не входил (см. [S2] спека) и остаётся открытым
