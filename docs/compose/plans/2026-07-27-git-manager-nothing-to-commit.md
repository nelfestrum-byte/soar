# Plan: GitManager "nothing to commit" — детерминированное определение (P16)

Спека: `docs/compose/specs/2026-07-27-git-manager-nothing-to-commit-design.md`

## Tests first

- [x] Добавить `test_git_manager_commit_nothing_with_untracked_file` в
      `tests/orchestrator/test_git_manager.py` — создать untracked-файл
      (`__pycache__/x.pyc`) в `git_repo` до вызова `commit("test.txt", ...)`
      без изменений `test.txt`; ожидать `commit_hash == ""`. Подтвердить,
      что тест падает (`RuntimeError`) на текущем коде.
- [x] Добавить `test_git_manager_commit_real_error_still_raises` — вызвать
      `commit()` с несуществующим/незастейженным путём файла, убедиться,
      что `RuntimeError` поднимается и на текущем, и на новом коде (не
      регрессия в тихий no-op).
- [x] Подтвердить, что существующий `test_git_manager_commit_nothing`
      остаётся зелёным без изменений.

## Implementation

- [x] Заменить тело `GitManager.commit()` в
      `orchestrator/core/git_manager.py` на версию из спеки [S2]: после
      `git add -- filepath` проверять `git diff --cached --quiet --
      filepath` через exit-код; `returncode == 0` → return `""` (реальный
      no-op); иначе выполнять `git commit` как раньше, но без
      string-match по stderr — любой ненулевой код после этого момента
      считается настоящей ошибкой и поднимает `RuntimeError`.
- [x] Убедиться, что `restore()` (использует `commit()` внутри) не требует
      изменений — получает фикс "бесплатно" по [S3].

## Verification

- [x] Запустить новые тесты — оба проходят после фикса.
- [x] Запустить полный `python -m pytest` — все тесты зелёные (4 несвязанных
      падения — внешний Redis/openapi, см. отчёт).

## Report

- [x] Написать `docs/compose/reports/git-manager-nothing-to-commit.md`
      после завершения.
