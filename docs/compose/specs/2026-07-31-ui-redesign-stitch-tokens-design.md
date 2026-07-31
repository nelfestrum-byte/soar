# UI-редизайн: Часть 5.1 — токены из результата Stitch

> Реализация Части 5.1 [`UI-REDESIGN.md`](../../concepts/UI-REDESIGN.md).
> Вход — экспорт Google Stitch в
> `docs/concepts/stitch_sentinel_soar_design_system/` (7 экранов +
> `sentinel_operator_interface/DESIGN.md` с токенами). Часть 3
> (структурные стадии — nav-группировка, `RowMenu`, editor-toolbar,
> `Loading`/`.empty`) уже реализована и закрыта отдельным отчётом
> (`docs/compose/reports/ui-redesign-structural.md`) — этот спек только
> меняет значения в `ui/src/styles/tokens.css`, разметку из Части 3 не
> трогает (кроме точечного перехода на иконки, см. [S4]).

## [S1] Problem

`ui/src/styles/tokens.css` сейчас содержит текущие (дореформенные)
hex-значения — Часть 3 перенесла точку изменения, но не изменила вид.
Экспорт Stitch даёт готовую тёмную M3-подобную палитру, типографику
(Inter/JetBrains Mono), spacing- и radius-шкалы — но не один-в-один
совместим с нашими 6 job-статусами и с требованием air-gap. Разбор:

### 1.1. Цветов для статусов меньше, чем статусов

Экспорт использует Material 3 роли: `primary` (циан `#4cd7f6`),
`secondary` (сине-лавандовый `#adc6ff`), `tertiary` (янтарь `#ffb873`),
`error` (коралловый `#ffb4ab`) — **четыре** смысловых цвета без
отдельного «success». Ни в одном из 7 `code.html` нет `green`/`emerald`/
`lime` ни в классах, ни в hex. Нашему приложению нужно **шесть**
различимых цветов (`pending/running/completed/failed/cancelled/
timeout`).

### 1.2. Danger и failed делят один и тот же красный

Исходный промпт Части 4 явно просил «danger/destructive color for
delete actions, clearly distinct from the failed-status color» — Stitch
этого не сделал: `error`/`on-error` используется и для деструктивных
кнопок, и для статуса `failed` (см. `workflows_data_tables/code.html:249`,
badge «Failed» — `text-error`/`bg-error/…`). Отдельного danger-тона нет
нигде в экспорте.

### 1.3. Шрифты и иконки — через Google Fonts CDN

Все 7 `code.html` тянут шрифты и Material Symbols рантаймом:
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:..." rel="stylesheet">
```
Продукт explicитно поддерживает air-gapped стенды (`deploy/soarctl
install` — «air-gapped target», `AGENTS.md`/`CLAUDE.md` — «зависимости
запекаются в образ... установки в рантайме нет»). Внешний CDN-запрос за
шрифтом при каждой загрузке страницы этому противоречит — на
изолированном стенде UI останется без Inter/JetBrains Mono/иконок
вообще (сеть недоступна), а не просто «уедет на дефолтный шрифт»: сама
попытка соединения с `fonts.googleapis.com` — то, чего на air-gap
стенде быть не должно.

### 1.4. Material Symbols — лигатурный шрифт, не набор SVG

Иконки задаются как `<span class="material-symbols-outlined">dashboard
</span>` — рендер через шрифт с лигатурами по имени глифа. Значит нужен
**весь** шрифт стиля (не набор из 15-20 SVG), это не точечная замена
пары символов.

## [S2] Solution — решения по находкам, форма и границы

Только `ui/`. Бэкенд не трогаем. Значения из Stitch заменяют текущие в
`tokens.css` — markup (Часть 3) не переписывается, кроме перехода части
глифов на Material Symbols ([S4]).

### Цвета статусов (1.1) — решение: добавить 2 цвета вне палитры Stitch

Все 4 M3-роли из экспорта используются без коллизий, плюс два новых
тона в том же стиле пары «светлый foreground / насыщенный container»,
что и у primary/tertiary/error:

| Статус | Роль | fg (текст/dot) | bg (container) |
|---|---|---|---|
| `pending` | `tertiary` (Stitch) | `#ffb873` | `#e89337` (10-15% opacity как фон бейджа, см. [S3]) |
| `running` | `primary` (Stitch) | `#4cd7f6` | `#06b6d4` |
| `completed` | **новый** `success` | `#6ee7b7` | `#10b981` |
| `failed` | `error` (Stitch) | `#ffb4ab` | `#93000a` |
| `cancelled` | `on-surface-variant`/`outline-variant` (Stitch, переиспользован) | `#bcc9cd` | `#3d494c` |
| `timeout` | `secondary` (Stitch) | `#adc6ff` | `#0566d9` |

`success`/`on-success` — единственные два значения во всём токен-сете,
не взятые из экспорта; подобраны в той же M3-логике (светлый пастельный
тон поверх насыщенного контейнера при тёмном фоне), чтобы не выбиваться
визуально. `cancelled` не требует нового цвета — это переиспользование
существующей нейтральной пары Stitch, а не добавление.

### Danger vs failed (1.2) — решение: не изобретать новый красный, развести тоном

Stitch дал только один красный. Вместо второго произвольного оттенка
(рискует не сочетаться с остальной палитрой) — разводим по
насыщенности и контексту применения, а не по hue:
- **Danger-кнопки** (`Delete`, деструктивные действия) — `error` +
  `on-error` (яркий коралл на тёмном), сплошная заливка, как обычная
  кнопка.
- **Badge `failed`** — `on-error-container`/`error-container` (глубокий
  бордовый `#93000a` фоном, `#ffdad6` текстом) — визуально плотный
  «ярлык», не кнопка.

Это тот же приём, что Stitch уже применяет для остальных статусов
(разные пары container/on-container), не новая идея — просто явно
проговорённая здесь, потому что предыдущий промпт просил другого и
результат нужно осознанно принять с отклонением.

### Шрифты/иконки (1.3, 1.4) — решение: самохостинг через `@fontsource`

Никаких `<link>` на `fonts.googleapis.com`. Три npm-пакета (версии на
момент проверки: `@fontsource/inter@5.3.0`,
`@fontsource/jetbrains-mono@5.3.0`,
`@fontsource/material-symbols-outlined@5.3.1`) — файлы шрифтов
запекаются в бандл на этапе `vite build` (внутри Docker build stage,
где есть сеть), рантайм контейнера их уже не качает — соответствует
принципу air-gap, ничем не отличается от того, как уже работают прочие
npm-зависимости `ui/`.

- Импортировать только нужные начертания: Inter 400/600/700,
  JetBrains Mono 400 — не весь пакет (у `@fontsource/inter`
  переменные веса лежат отдельными css-файлами, `import
  '@fontsource/inter/400.css'` и т.д., не весь `index.css`).
- Material Symbols — **один** стиль (Outlined, как в макетах Stitch),
  не три (Outlined/Rounded/Sharp). Это всё равно лигатурный шрифт
  целиком (не подмножество на 15-20 иконок, см. 1.4) — вес учтён как
  риск в [S5], не устраняется, только ограничивается одним стилем.
- `@font-face`/импорт — в новом `ui/src/styles/fonts.css`, подключается
  из `main.js` рядом с `tokens.css`.

### [S4] Иконки в разметке — точечно, не тотальная замена

Замена unicode-глифов на Material Symbols — только там, где иконка уже
есть в макетах Stitch и не требует расширения текущей разметки Части 3:
`⚙` (nav More toggle) → `settings`, `⋮` (RowMenu toggle) → `more_vert`,
`▾`/`▸` (Workflows detail toggle, editor tab chevroны) →
`expand_more`/`chevron_right`. Остальной текст кнопок (Save/Close/Edit/
Delete/Audit...) остаётся текстом — Stitch тоже использует текст+иконку
вместе, не заменяет подписи пиктограммами.

## [S3] Токены — полный список изменений в `tokens.css`

Спейсинг и радиусы — берутся шкалой целиком (было 2 значения радиуса,
станет 5; было 6 интервалов, станет 8):

```css
/* radius — было --radius/--radius-lg, добавляются промежуточные */
--radius-sm: 2px;    /* было отсутствует */
--radius: 4px;        /* не меняется */
--radius-md: 6px;     /* новое */
--radius-lg: 8px;     /* не меняется */
--radius-xl: 12px;    /* новое */
--radius-full: 9999px;/* новое — status-badge/pill */

/* spacing — добавляются 2 больших шага */
--space-1: 4px; --space-2: 8px; --space-3: 12px;
--space-4: 16px; --space-5: 24px; --space-6: 32px;
--space-7: 48px; /* новое */
--space-8: 64px; /* новое */

/* типографика — новая категория токенов, до этого не было */
--font-sans: 'Inter', sans-serif;
--font-mono: 'JetBrains Mono', monospace; /* было monospace без имени */
--text-h1: 24px; --text-h1-weight: 600; --text-h1-line: 32px; --text-h1-tracking: -0.02em;
--text-h2: 20px; --text-h2-weight: 600; --text-h2-line: 28px; --text-h2-tracking: -0.01em;
--text-h3: 16px; --text-h3-weight: 600; --text-h3-line: 24px;
--text-body: 14px; --text-body-line: 20px;
--text-body-sm: 12px; --text-body-sm-line: 16px;
--text-code: 13px; --text-code-line: 18px;
--text-label-caps: 11px; --text-label-caps-line: 16px; --text-label-caps-tracking: 0.05em;
```

Цвета — полная замена (значения из `DESIGN.md`, статус-пары — из [S2]):

```css
/* поверхности */
--color-surface: #0b1326;
--color-surface-alt: #171f33;       /* было #fafafa (светлая!) — surface-container */
--color-surface-dark: #060e20;      /* было #1a1a2e — surface-container-lowest, для nav/pre */
--color-surface-hover: #222a3d;     /* было #f5f7fa — surface-container-high */

/* текст */
--color-text: #dae2fd;              /* было #333 (тёмный на светлом!) — on-surface */
--color-text-muted: #bcc9cd;        /* было #666/#555 — on-surface-variant */
--color-text-faint: #869397;        /* было #999/#888/#aaa/#ccc — outline */
--color-text-on-dark: #dae2fd;      /* текст в <pre>, был зелёный #a5d6a7 — теперь единый on-surface */

/* границы */
--color-border: #3d494c;            /* было #ddd — outline-variant */
--color-border-subtle: #2d3449;     /* было #eee — surface-variant */

/* акцент/действия */
--color-accent: #4cd7f6;            /* было #4fc3f7 — очень близко, почти не меняется */
--color-accent-fg: #003640;         /* было #000 — on-primary */
--color-danger: #ffb4ab;            /* было #ef5350 — error */
--color-success: #6ee7b7;           /* было #66bb6a — новый success (см. [S2]) */
--color-result-ok: #10b981;         /* было #2e7d32 — success-container (насыщенный) */
--color-result-fail: #93000a;       /* было #c62828 — error-container */

/* статус-бейджи — таблица [S2] */
--status-pending-bg: #e89337;   --status-pending-fg: #ffb873;
--status-running-bg: #06b6d4;   --status-running-fg: #4cd7f6;
--status-completed-bg: #10b981; --status-completed-fg: #6ee7b7;
--status-failed-bg: #93000a;    --status-failed-fg: #ffdad6;
--status-cancelled-bg: #3d494c; --status-cancelled-fg: #bcc9cd;
--status-timeout-bg: #0566d9;   --status-timeout-fg: #adc6ff;
```

**Важно про смену темы**: приложение было светлым (`--color-surface:
#fff`), становится тёмным (`--color-surface: #0b1326`) — это Часть 5.1
целиком, ровно тот смысл, ради которого затевался весь концепт. Это
меняет `<body>`/`.card`/таблицы визуально полностью (задача Части 5.2 —
переключить сами классы на `var()`, но они уже это делают с Части 3,
поэтому смена значений в `tokens.css` перекрашивает приложение сразу,
без правки `App.vue`).

Светлая тема из `DESIGN.md` не описана количественно (Stitch отдал
только тёмный вариант, несмотря на то что в промпте Части 4 просили
«also provide a light-mode variant») — светлой темы в этом спеке нет,
фиксирую как известное ограничение, не блокирует внедрение тёмной.

## [S5] Границы и риски

- **Не трогаем разметку Части 3**, кроме [S4] (иконки на месте
  существующих глифов) — ни nav, ни `RowMenu`, ни toolbar
  структурно не меняются, меняется только то, чем они закрашены.
- **Не делаем светлую тему** — нет данных от Stitch, отдельная задача.
- **Вес бандла**: три самохощенных шрифта + один стиль иконочного
  шрифта — не измерено в этом спеке точное число КБ после
  `vite build`, будет зафиксировано в отчёте по факту сборки. Если оно
  окажется существенным (сопоставимо с рисками Monaco из Части 2) — это
  повод для отдельного решения (например, `font-display: swap` уже
  входит в план, subset по diapason можно рассмотреть отдельно), не
  для отмены самохостинга (air-gap важнее веса).
- **Не Часть 5.2/5.3/5.4** — глобальные классы уже на `var()` (Часть 3
  подготовила почву), доп. работы по nav/row actions/Monaco не входят.

## [S6] Testing Strategy

- Расширить `ui/tests/tokens.spec.js`: проверка полного нового набора
  имён переменных (radius-sm/md/xl/full, space-7/8, text-*, font-sans) —
  та же логика, что уже есть для старого набора.
- Новый `ui/tests/fonts.spec.js` — читает `ui/src/styles/fonts.css`,
  проверяет отсутствие `fonts.googleapis.com`/любого `http`-URL в
  `@import`/`url()` (регрессионный тест на «не откатились на CDN»).
- Ручной чек в отчёте: `npm run build`, сравнить размер `dist/assets`
  до/после (зафиксировать в отчёте, не в тесте).
- Существующие 4 vitest-теста на цвета (`row-menu`, `nav`, `loading`,
  `editor-toolbar`) не должны затронуться — они проверяют
  структуру/поведение, не конкретные hex.

## [S7] Success Criteria

- [ ] `tokens.css` — все значения из таблиц [S3] применены, старые
      hex не остались
- [ ] Никаких запросов к `fonts.googleapis.com`/другому внешнему CDN —
      шрифты и иконки из `node_modules/@fontsource/*`, упакованы в
      `dist/`
- [ ] 6 статус-цветов различимы между собой (проверка глазами, не
      автоматизирована — colorblind-safe заявлено дизайн-системой для
      её 4 базовых ролей, 2 новых подбирались в том же тоне)
- [ ] `npm test` зелёный, `npm run build` без ошибок
- [ ] Ни одной правки в `orchestrator/`/`soar/`
