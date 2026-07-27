# GitManager: детерминированное определение "нечего коммитить"

> Реализует P16 из `docs/concepts/UPGRADE-v2.md` (known-limitation #7).
> Убирает string-match по stderr git'а в `GitManager.commit()`, который
> пропускает часть реальных формулировок git и потенциально зависит от
> локали окружения — из-за чего мутация применяется, а audit-запись
> тихо теряется.

## [S1] Problem

`GitManager.commit()` (`orchestrator/core/git_manager.py:53-83`) после
неудачного `git commit` смотрит на подстроку в `stdout+stderr`:

```python
if "nothing to commit" in combined or "no changes" in combined:
    return ""
raise RuntimeError(f"git commit failed: {stderr.decode()}")
```

Git формулирует "нечего коммитить" по-разному в зависимости от того, есть
ли в рабочей директории untracked-файлы:

- чисто → `nothing to commit, working tree clean` — матчится
- есть untracked (`__pycache__`, генерируемые файлы workflows/actions/
  connectors) → `nothing added to commit but untracked files present
  (use "git add" to track)` — **не содержит** подстроку `"nothing to
  commit"**, не матчится**

Во втором случае метод кидает `RuntimeError`, хотя семантически это тот же
случай "для этого файла нечего коммитить". На call-site'ах (`orchestrator/
api/workflows.py:300-301`, аналогично `actions.py:189`, `connectors.py:263,
416,522,571,601`, `prompts.py:53`) это ловится и делает ранний `return` до
`audit_service.record()` — файл записан на диск, но ни коммита, ни
audit-записи не остаётся. Обнаружено вручную при проверке UI (2026-07-18),
задокументировано как known-limitation #7.

Есть более широкая проблема с тем же корнем: `_run()`/`commit()` не
форсируют `LC_ALL=C` в env субпроцесса (`git_manager.py:23-29,61-67`) — на
сервере с не-английской локалью git может писать сообщение об ошибке не по-
английски, и тогда матч `"nothing to commit"` не сработает вообще ни в
одном случае, а не только в untracked-сценарии. Расширение списка
подстрок (добавить `"nothing added to commit"`) закрыло бы конкретный
репортнутый случай, но не устраняет эту хрупкость в целом.

**Рассмотрено и отклонено:**
- **Расширить string-match** (`"nothing to commit" in combined or
  "nothing added to commit" in combined or ...`) — закрывает конкретный
  баг, но оставляет метод зависимым от текста, который git не гарантирует
  как стабильный API; локаль-зависимость остаётся нерешённой.
- **Форсировать `LC_ALL=C` и оставить string-match** — решает локаль-
  проблему, но не убирает саму хрупкость парсинга человекочитаемого
  вывода как источника истины; будущая новая формулировка git (напр. при
  других флагах коммита) снова тихо всплывёт тем же классом бага.
- **`.gitignore` для `__pycache__` в `config.git.workflows_repo`** —
  устраняет конкретный триггер (untracked-файлы), но не сам баг: любая
  другая причина появления untracked-файлов в рабочей директории (ручное
  вмешательство оператора, будущий workflow, оставляющий temp-файлы)
  воспроизведёт проблему снова. Не отменяет [S2] — как гигиена репозитория
  может быть сделана отдельно, вне этого спека.

## [S2] Solution

Заменить парсинг текста ошибки на проверку через exit-код `git diff
--cached --quiet` сразу после `git add` — единственный источник истины
"застейджено ли что-то для этого файла для коммита", не зависящий от
языка вывода git и не чувствительный к присутствию посторонних
untracked-файлов в рабочей директории:

```python
async def commit(
    self, filepath: str, message: str,
    author_name: str | None = None, author_email: str | None = None,
) -> str:
    name = author_name or self.author_name
    email = author_email or self.author_email

    await self._run("add", "--", filepath)

    diff_proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet", "--", filepath,
        cwd=self.repo_path,
    )
    await diff_proc.wait()
    if diff_proc.returncode == 0:
        return ""  # ничего не застейджено для filepath — реальный no-op

    env = {...}  # без изменений
    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", message,
        f"--author={name} <{email}>",
        cwd=self.repo_path,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git commit failed: {stderr.decode()}")
    result = await self._run("rev-parse", "--short", "HEAD")
    return result.strip()
```

Убирается весь блок `combined = ...; if "nothing to commit" in combined or
"no changes" in combined`. После `diff --cached --quiet` возврата `0`
любой ненулевой код из `git commit` — уже настоящая ошибка (права доступа,
hook и т.п.), не требует больше угадывания по тексту.

`ensure_repo()` гарантирует, что к моменту вызова `commit()` в репозитории
всегда есть хотя бы один коммит (`Initial commit` при `init`), поэтому
`git diff --cached` всегда сравнивает с существующим `HEAD` — сценарий
"нет HEAD" не возникает.

## [S3] Behavior change

- Для `commit()` — только внутренняя реализация, публичный контракт
  (`str` hash или `""`) не меняется. Все текущие call-site'ы (`workflows.py`,
  `actions.py`, `connectors.py`, `prompts.py`) продолжают работать как
  раньше **и** теперь дополнительно корректно проходят audit-record в
  untracked-файлы-сценарии, где раньше падали в `RuntimeError`.
- `restore()` (`git_manager.py:110-118`) вызывает `commit()` внутри — тоже
  получает исправление бесплатно.

## [S4] Out of scope

- `.gitignore` для `__pycache__`/генерируемых файлов в
  `config.git.workflows_repo` — отдельная гигиена репозитория, не входит в
  этот спек ([S1], "Рассмотрено и отклонено"). Может быть сделана
  отдельным точечным изменением при желании, но не нужна для закрытия
  P16/known-limitation #7 после [S2].
- `LC_ALL=C` в env субпроцессов — становится ненужным для этого конкретного
  метода после [S2] (не парсим текст вывода), но `_run()` использует те же
  env-паттерны для `history`/`get_content`/`diff`, где вывод парсится
  структурно (`\x00`-разделители, не человекочитаемый текст) — локаль там
  не создаёт этот класс проблемы. Не трогается в этом спеке.

## [S5] Tests

Новые/изменённые в `tests/orchestrator/test_git_manager.py`:

- `test_git_manager_commit_nothing` (уже существует, `git_repo` без
  untracked-файлов) — остаётся зелёным без изменений, проверяет старый
  путь `diff --cached --quiet` возвращает `0` в чистом дереве.
- **Новый** `test_git_manager_commit_nothing_with_untracked_file` —
  воспроизводит репортнутый баг: создать untracked-файл (`__pycache__/x.pyc`
  или любой другой) в `git_repo` **до** вызова `commit("test.txt", ...)` без
  изменений `test.txt`; ожидать `commit_hash == ""`, без `RuntimeError`.
  Это тест, который падал бы на текущем коде (`RuntimeError`) и проходит
  после [S2] — воспроизводит known-limitation #7 напрямую.
- **Новый** `test_git_manager_commit_real_error_still_raises` — убедиться,
  что реальная ошибка (напр. `filepath`, которого не существует и не был
  застейджен ранее — `git commit` без `--allow-empty` и без изменений
  по несуществующему пути) всё ещё поднимает `RuntimeError`, чтобы
  regression не превратил все ошибки коммита в тихий `""`.
