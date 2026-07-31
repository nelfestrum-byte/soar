# SOAR

Минималистичный SOAR: детерминированные автоматические расследования на
ECS-схеме и авто-закрытие типовых кейсов с ложными срабатываниями — без
LLM внутри движка. Каждое решение объяснимо и воспроизводимо: путь от
алерта до вердикта виден целиком, ничего не решается "по вероятности".

При этом сам SOAR спроектирован под LLM-агентскую разработку: API отдаёт
самоописание коннекторов/actions/workflow без чтения исходников,
проверяет код при сохранении и возвращает полный traceback вместо
`str(error)` — агент может писать и чинить интеграции прямо в живой
инфраструктуре, а не только по документации. Любое изменение кода
версионируется через git — история, diff и restore доступны из коробки,
как и полный аудит запросов и security-событий.

## Быстрый старт (локально)

```bash
python -m pip install -r orchestrator/requirements.txt
python -m uvicorn orchestrator.main:app --reload --port 8000
```

Без `config.yaml` в рабочей директории сервис стартует с дефолтами:
SQLite-файл `./soar.db`, in-memory очередь, auth выключена (анонимный
admin). API — `http://localhost:8000/status`, Swagger —
`http://localhost:8000/docs`.

```bash
python -m pytest tests/ -v
ruff check .
mypy orchestrator/ soar/ --ignore-missing-imports
```

## Деплой — `soarctl`

**On-site** (машина сама имеет доступ в интернет — checkout это инстанс,
без отдельной директории):

```bash
git clone <url> soar && cd soar
./soarctl install                   # docker build локально
./soarctl init --interactive        # .env + config.yaml, спросит auth.cors_origins
./soarctl up
./soarctl migrate --fresh           # первый деплой (см. deploy/prod/README.md — fresh vs upgrade)
./soarctl users create --username admin --role admin
```

Обновление — `./soarctl update --ref vX.Y.Z && ./soarctl migrate --fresh`
(если релиз принёс миграцию). Любая подкоманда сама находит рабочую
директорию от текущего каталога вверх — вызывать можно из любого
подкаталога чекаута, `--dir` не нужен.

**Air-gapped** (сборка на машине с интернетом → перенос бандла →
установка офлайн):

```bash
python deploy/soarctl package --version X.Y.Z --output soar-bundle-X.Y.Z.tar.gz
# перенести файл на целевую машину (USB/scp)
python soarctl install soar-bundle-X.Y.Z.tar.gz --dir soar-prod && cd soar-prod
python soarctl init && python soarctl up && python soarctl migrate --fresh
```

День-2 операции (оба варианта): `soarctl status` / `logs [service]` /
`backup create --output ...` / `backup restore ... --confirm` / `down`.

Подробнее — [`deploy/prod/README.md`](deploy/prod/README.md).

## Документация

- [AGENTS.md](AGENTS.md) — архитектура, паттерны, команды: источник
  истины для разработки (в том числе для агентов, читающих этот repo)
- [docs/agents/known-limitations.md](docs/agents/known-limitations.md) — известные ограничения
- [docs/concepts/BAGFIX_PLAN.md](docs/concepts/BAGFIX_PLAN.md) — трек багфикса перед пилотом
- [CHANGELOG.md](CHANGELOG.md) — история версий

## Осознанное ограничение: без изоляции workflow

Workflow выполняются как обычный subprocess на том же хосте — без
контейнеризации или sandbox на каждый job. Это осознанный компромисс
ради скорости и простоты, а не недосмотр: проект — SOAR для
автоматизации конкретных сценариев расследования security-кейсов, а не
универсальная платформа для запуска недоверенного кода в масштабах
всей компании. Код workflow должен быть таким же доверенным, как
остальной кодбейз.
