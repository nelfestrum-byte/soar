# SOAR

Минималистичный SOAR (Security Orchestration, Automation and Response) без
LLM: детерминированные автоматические расследования на ECS-схеме,
автоматическое закрытие стандартных кейсов с ложными срабатываниями.

Архитектура, конфигурация, auth, логи, известные ограничения — в
[AGENTS.md](AGENTS.md).

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
