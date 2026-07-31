# Plan: UI-редизайн, Часть 5.1 — токены из результата Stitch

Спека: `docs/compose/specs/2026-07-31-ui-redesign-stitch-tokens-design.md`
Источник: `docs/concepts/stitch_sentinel_soar_design_system/`.

**Порядок:** Часть 1 (шрифты/иконки) перед Частью 2 (цвета/типографика/
spacing в `tokens.css`) — токены типографики ссылаются на
`--font-sans`/`--font-mono`, которые должны существовать раньше.
Часть 3 (иконки в разметке, [S4]) — последняя, независима от 1/2 по
содержанию, но естественно идёт после того, как шрифт иконок подключён.

---

## Часть 1 — самохостинг шрифтов и иконок

### Тесты первыми (`ui/tests/fonts.spec.js`, новый файл)

- [ ] `test('fonts.css has no external font CDN references')` —
      читает `ui/src/styles/fonts.css`, regex на `fonts\.googleapis\.com`
      и на `url\(https?:` — ожидание: ноль совпадений. Падает сейчас
      (файла нет вовсе → тест ошибается на чтении, что и есть красное
      состояние).
- [ ] `test('main.js does not link an external font stylesheet')` —
      читает `ui/src/main.js` и `ui/index.html`, тот же regex на
      `fonts.googleapis.com` — регрессионный тест на «не откатились на
      `<link>`».

### Implementation

- [ ] `npm install @fontsource/inter @fontsource/jetbrains-mono
      @fontsource/material-symbols-outlined` в `ui/`.
- [ ] Новый `ui/src/styles/fonts.css`:
      `@import '@fontsource/inter/400.css';`,
      `/600.css`, `/700.css`, `@fontsource/jetbrains-mono/400.css`,
      `@fontsource/material-symbols-outlined` (стиль Outlined, один
      статический вес — свериться, какой конкретно css-файл пакет
      экспортирует для лигатурного рендера по классу
      `.material-symbols-outlined`, аналог `<span
      class="material-symbols-outlined">`).
- [ ] `ui/index.html` — удалить (если есть) любые `<link
      href="https://fonts.googleapis.com/...">`; их не должно быть,
      проверить на всякий случай (Stitch-макеты их вставляли в свои
      `code.html`, наш `index.html` их никогда не имел, но явная
      проверка дешевле, чем ошибка предположения).
- [ ] Импортировать `fonts.css` в `ui/src/main.js` рядом с
      `tokens.css` (`import './styles/fonts.css'`).
- [ ] Замерить `du -sh ui/node_modules/@fontsource/*` и после
      `npm run build` — размер `dist/assets/*.woff2` — зафиксировать в
      отчёте (не тест, ручная проверка [S5] спеки).

---

## Часть 2 — токены `tokens.css`

### Тесты первыми (расширение `ui/tests/tokens.spec.js`)

- [ ] Расширить список `required` в существующем тесте «defines every
      semantic color and scale variable» — добавить `--radius-sm`,
      `--radius-md`, `--radius-xl`, `--radius-full`, `--space-7`,
      `--space-8`, `--font-sans`, `--font-mono` (уже есть, не трогать),
      `--text-h1`, `--text-h1-weight`, `--text-h1-line`,
      `--text-h1-tracking`, `--text-h2*`, `--text-h3*`, `--text-body*`,
      `--text-code*`, `--text-label-caps*` (полный список — [S3] спеки).
      Тест падает сейчас (новых переменных ещё нет).
- [ ] Новый тест `test('status colors are six distinct hues, not four')`
      — парсит 6 пар `--status-*-fg` из `tokens.css`, проверяет, что
      все 6 значений `-fg` попарно различны (`new Set(values).size ===
      6`) — ловит именно найденную в спеке проблему (4 цвета на 6
      статусов), а не будущий откат к ней.
- [ ] Существующий тест «no raw hex color literals remain outside
      tokens.css» — не трогать, должен остаться зелёным (значения
      меняются только внутри `tokens.css`, markup — нет).

### Implementation

- [ ] `ui/src/styles/tokens.css` — заменить значения по таблицам [S3]
      спеки: поверхности, текст, границы, акцент/danger/success,
      6 статус-пар, добавить `--space-7/8`, `--radius-sm/md/xl/full`,
      блок `--text-*`/`--font-sans`.
- [ ] Прогнать визуально (`npm run dev`, см. Verification) — приложение
      должно стать тёмным целиком без правки `App.vue`/вьюх (Часть 3
      уже посадила глобальные классы на `var()`).

---

## Часть 3 — иконки в разметке ([S4])

### Тесты первыми

- [ ] `ui/tests/nav.spec.js` — заменить проверку текста toggle-кнопки
      (если тест искал `⚙ More` буквально) на проверку класса иконки
      `.material-symbols-outlined` внутри `[data-test="nav-more-toggle"]`
      + видимый текст `More` рядом. Сверить точную текущую assertion
      перед правкой — не сломать её случайно.
- [ ] `ui/tests/row-menu.spec.js` — аналогично: toggle рендерит иконку
      `more_vert`, не буквальный `⋮`.

### Implementation

- [ ] `App.vue` — `⚙` → `<span class="material-symbols-outlined">settings</span>`
      в nav more-toggle.
- [ ] `RowMenu.vue` — `⋮` → `more_vert`.
- [ ] `Workflows.vue` — `▾`/`▸` (detail-toggle) →
      `expand_more`/`chevron_right`.
- [ ] Вкладки редактора (Code/History/Config/Signature) — текст
      остаётся текстом, иконки не добавляются (Stitch у вкладок тоже
      держит и иконку, и подпись вместе — но добавление иконок к каждой
      вкладке не входит в список точечных замен [S4], это уже
      расширение, не перенос).

---

## Verification

- [ ] `cd ui && npm test` — все новые и существующие тесты зелёные
- [ ] `grep -rE "fonts\.googleapis\.com" ui/src ui/index.html` — пусто
- [ ] `cd ui && npm run build` — без ошибок; зафиксировать в отчёте
      суммарный размер новых шрифтовых ассетов в `dist/assets`
- [ ] `cd ui && npm run dev` — визуально: приложение тёмное, 6 статусов
      различимы на таблице Jobs/бейджах, nav more-toggle и RowMenu
      показывают иконки, а не только текст/юникод
- [ ] Ни одной правки в `orchestrator/`/`soar/`
- [ ] Написать отчёт `docs/compose/reports/ui-redesign-stitch-tokens.md`,
      отметить в `docs/concepts/UI-REDESIGN.md` чеклист "Часть 5.1"
      выполненным
