# Report: GitManager "nothing to commit" — детерминированное определение (P16)

Спека: `docs/compose/specs/2026-07-27-git-manager-nothing-to-commit-design.md`
План: `docs/compose/plans/2026-07-27-git-manager-nothing-to-commit.md`

## Что сделано

`GitManager.commit()` (`orchestrator/core/git_manager.py`) больше не
определяет "нечего коммитить" парсингом текста stderr/stdout git'а.
Вместо этого после `git add -- filepath` выполняется `git diff --cached
--quiet -- filepath`: `returncode == 0` означает, что для данного файла
ничего не застейджено — гарантированный no-op, `commit()` возвращает `""`.
Любой ненулевой код от последующего `git commit` теперь однозначно
считается настоящей ошибкой и поднимает `RuntimeError` — блок
`combined = ...; if "nothing to commit" in combined or "no changes" in
combined` удалён полностью, как и предписано в [S2] спеки.

Публичный контракт `commit()` не изменился (по-прежнему `str`: hash или
`""`). `restore()` использует `commit()` внутри и получает исправление без
дополнительных правок ([S3]).

## Изменённые файлы

- `orchestrator/core/git_manager.py` — тело `commit()` заменено на версию
  из [S2]: exit-код `git diff --cached --quiet` вместо string-match по
  тексту ошибки.
- `tests/orchestrator/test_git_manager.py` — добавлены два теста:
  - `test_git_manager_commit_nothing_with_untracked_file` — создаёт
    untracked-файл (`__pycache__/x.pyc`) до вызова `commit("test.txt", ...)`
    без изменений `test.txt`; ожидает `commit_hash == ""`. На текущем
    (до фикса) коде тест падал с `RuntimeError` (подтверждено запуском
    до внесения фикса) — воспроизводит known-limitation #7 напрямую.
  - `test_git_manager_commit_real_error_still_raises` — вызывает
    `commit()` с несуществующим/незастейженным путём файла, убеждается,
    что `RuntimeError` по-прежнему поднимается (regression guard: любые
    реальные ошибки не должны молча превращаться в `""`).
- `docs/compose/plans/2026-07-27-git-manager-nothing-to-commit.md` — план
  (новый файл).

## Test-first подтверждение

Перед внесением фикса запущены только новые тесты против текущего кода:

```
tests/orchestrator/test_git_manager.py::test_git_manager_commit_nothing_with_untracked_file FAILED (RuntimeError)
tests/orchestrator/test_git_manager.py::test_git_manager_commit_real_error_still_raises PASSED
```

Первый тест воспроизвёл баг (`RuntimeError` вместо `""`), как и ожидалось
по спеке. Второй тест уже проходил и до фикса (это ожидаемо — он
регрессионный guard, а не воспроизведение бага).

## Результат после фикса

`tests/orchestrator/test_git_manager.py` — 10/10 passed, включая оба новых
теста и неизменный `test_git_manager_commit_nothing`.

Полный набор: `python -m pytest` →
**598 passed, 4 failed, 1 skipped** (601 tests total, +2 новых = 610 items
в файле git_manager, но общий счётчик suite не поменялся кроме двух новых
тестов).

4 failing тестов не связаны с этим изменением и не зависят от него:
`tests/orchestrator/test_redis_integration.py::test_redis_integration_push_pop`,
`test_redis_integration_multiple_jobs`, `test_redis_integration_clear`
(требуют внешний Redis-сервер, недоступный в этом окружении) и
`tests/soar/tools/test_openapi.py::test_generate_config` (несвязанный
инструмент). Подтверждено запуском тех же тестов на `git stash` (без
изменений git_manager) — тот же результат: 4 failed, независимо от этого
фикса.

## Out of scope (не тронуто, по [S4])

- `.gitignore` для `__pycache__`/генерируемых файлов —
  не входит в этот спек.
- `LC_ALL=C` в env субпроцессов `_run()` — не требуется для `commit()`
  после [S2], не трогалось.
