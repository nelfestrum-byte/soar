# SOAR Orchestrator

Ты пишешь отдельный сервис-оркестратор для SOAR модуля. Это самостоятельный Docker-контейнер с FastAPI, очередью задач, пулом воркеров и git-версионированием файлов. UI пишется отдельно на Vue.js и работает через API этого сервиса. Авторизации нет — сервис доверяет локальным соединениям внутри Docker-сети.

## Стек

- Python 3.11+
- fastapi + uvicorn — HTTP сервер
- apscheduler — запуск scheduled workflows по расписанию
- pyyaml — конфиг оркестратора и состояние workflows
- sse-starlette — SSE стрим логов
- redis — опциональный бэкенд очереди (только если backend: redis в конфиге)
- loguru — логирование
- git (системный) — версионирование файлов workflows через subprocess

## Структура проекта

```
orchestrator/
├── CLAUDE.md
├── Dockerfile
├── requirements.txt
├── config.yaml                      # конфиг оркестратора
├── orchestrator_state.yaml          # enable/disable workflows, НЕ в git
├── main.py                          # FastAPI app + lifespan
├── config.py                        # Pydantic Settings, читает config.yaml
├── api/
│   ├── __init__.py
│   ├── workflows.py                 # GET/POST/DELETE метаданные и enable/disable
│   ├── files.py                     # GET/PUT содержимое файлов + история git
│   ├── jobs.py                      # запуск, статус, отмена job
│   ├── webhooks.py                  # POST /webhooks/{workflow_name}
│   ├── logs.py                      # SSE стрим логов job
│   └── status.py                    # GET /status — воркеры, очередь, статистика
├── core/
│   ├── queue/
│   │   ├── base.py                  # AbstractJobQueue (ABC)
│   │   ├── memory.py                # InMemoryQueue
│   │   └── redis_queue.py           # RedisQueue
│   ├── worker.py                    # Worker — один воркер, разбирает очередь
│   ├── worker_pool.py               # WorkerPool — N воркеров из конфига
│   ├── scheduler.py                 # OrchestratorScheduler (APScheduler)
│   ├── job_manager.py               # JobManager — координатор
│   ├── subprocess_runner.py         # запуск workflow как subprocess + timeout
│   └── git_manager.py               # git операции над директорией workflows
├── models/
│   ├── job.py                       # WorkflowJob, JobStatus, ConcurrencyPolicy
│   └── workflow_meta.py             # WorkflowMeta — метаданные из registry
└── store/
    └── job_store.py                 # JobStore — хранение jobs в памяти (v1)
```

## Конфиг (config.yaml)

```yaml
workers:
  count: 4
  default_timeout: 300        # секунды, глобальный дефолт таймаута

queue:
  backend: memory             # memory | redis
  redis_url: redis://localhost:6379/0

soar:
  workflows_dir: /app/soar/workflows
  connectors_dir: /app/soar/connectors
  actions_dir: /app/soar/actions

git:
  workflows_repo: /app/soar   # корень git-репозитория
  author_name: SOAR Orchestrator
  author_email: soar@local

logging:
  level: INFO
  file: /var/log/soar/orchestrator.log

jobs:
  log_dir: /var/log/soar/jobs
  keep_completed: 1000        # сколько завершённых jobs хранить в памяти
```

## Модели (models/)

### JobStatus

```python
class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    TIMEOUT   = "timeout"
    CANCELLED = "cancelled"
```

### ConcurrencyPolicy

```python
class ConcurrencyPolicy(str, Enum):
    FORBID = "forbid"    # нельзя запустить если уже running — дефолт для Manual
    QUEUE  = "queue"     # встать в очередь — дефолт для Scheduled
    ALLOW  = "allow"     # параллельный запуск без ограничений
```

### WorkflowJob

```python
@dataclass
class WorkflowJob:
    id:             str           # uuid4
    workflow_name:  str
    workflow_type:  str           # scheduled | webhook | manual
    triggered_by:   str           # user / scheduler / webhook
    context:        dict          # входные параметры

    status:         JobStatus     = JobStatus.PENDING
    pid:            int | None    = None
    log_path:       str | None    = None

    triggered_at:   datetime      = field(default_factory=lambda: datetime.now(UTC))
    started_at:     datetime | None = None
    finished_at:    datetime | None = None

    result_success: bool | None   = None
    result_data:    dict | None   = None
    result_error:   str | None    = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
```

### WorkflowMeta

```python
@dataclass
class WorkflowMeta:
    name:        str
    type:        str              # scheduled | webhook | manual
    enabled:     bool
    # scheduled
    schedule:    str | None       # cron выражение
    interval:    int | None       # секунды
    # webhook
    path:        str | None
    token:       str | None
    # общие
    timeout:     int | None       # переопределяет глобальный дефолт
    concurrency: ConcurrencyPolicy
    file_path:   str              # абсолютный путь к .py файлу
```

## Очередь (core/queue/)

### AbstractJobQueue

```python
class AbstractJobQueue(ABC):
    @abstractmethod
    async def push(self, job: WorkflowJob) -> None: ...

    @abstractmethod
    async def pop(self, timeout: float = 1.0) -> WorkflowJob | None: ...
    # возвращает None если очередь пуста за timeout секунд

    @abstractmethod
    async def size(self) -> int: ...

    @abstractmethod
    async def clear(self) -> None: ...
```

### InMemoryQueue

asyncio.Queue внутри. pop реализовать через asyncio.wait_for(queue.get(), timeout).

### RedisQueue

Список в Redis (LPUSH / BRPOP). Сериализация job — JSON. Включается когда `config.queue.backend == "redis"`.

### Выбор бэкенда в main.py

```python
def create_queue(config) -> AbstractJobQueue:
    if config.queue.backend == "redis":
        return RedisQueue(config.queue.redis_url)
    return InMemoryQueue()
```

## Воркеры (core/worker.py, core/worker_pool.py)

### Worker

```python
class Worker:
    def __init__(self, worker_id: int, queue: AbstractJobQueue,
                 runner: SubprocessRunner, job_store: JobStore, config): ...

    async def run(self) -> None:
        # основной цикл — живёт пока self._running
        while self._running:
            job = await self.queue.pop(timeout=1.0)
            if job:
                await self._execute(job)

    async def _execute(self, job: WorkflowJob) -> None:
        # 1. обновить статус → RUNNING, записать started_at, pid
        # 2. запустить subprocess через runner
        # 3. ждать завершения с таймаутом
        # 4. при TimeoutError — kill процесса, статус → TIMEOUT
        # 5. читать результат из log_path / stdout
        # 6. обновить статус → COMPLETED | FAILED

    @property
    def is_busy(self) -> bool: ...

    async def stop(self) -> None: ...
```

Таймаут берётся из `job.timeout or config.workers.default_timeout`.

### WorkerPool

```python
class WorkerPool:
    def __init__(self, count: int, queue, runner, job_store, config): ...

    async def start(self) -> None:
        # создать и запустить count воркеров как asyncio tasks

    async def stop(self) -> None:
        # graceful stop всех воркеров

    @property
    def status(self) -> dict:
        return {
            "total": len(self._workers),
            "busy": sum(1 for w in self._workers if w.is_busy),
            "idle": sum(1 for w in self._workers if not w.is_busy),
        }
```

## Subprocess Runner (core/subprocess_runner.py)

Запускает workflow как отдельный процесс. Передаёт контекст через переменную окружения. Результат workflow пишется в log_path.

```python
class SubprocessRunner:
    async def start(self, job: WorkflowJob) -> asyncio.subprocess.Process:
        env = {
            **os.environ,
            "SOAR_JOB_ID": job.id,
            "SOAR_WORKFLOW_NAME": job.workflow_name,
            "SOAR_CONTEXT": json.dumps(job.context),
            "SOAR_LOG_PATH": job.log_path,
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "soar.runner",   # точка входа в SOAR модуле
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return proc
```

`soar.runner` — модуль внутри SOAR пакета, читает env, запускает `workflows.execute(name, context)`, пишет `WorkflowResult` как JSON в stdout последней строкой.

Лог каждого job — отдельный файл:
```
/var/log/soar/jobs/{workflow_name}/{job_id}.log
```

## Scheduler (core/scheduler.py)

```python
class OrchestratorScheduler:
    def __init__(self, job_manager: JobManager): ...

    async def start(self, workflows: list[WorkflowMeta]) -> None:
        # регистрирует только enabled scheduled workflows
        # при добавлении/удалении workflow — reload()

    async def reload(self, workflows: list[WorkflowMeta]) -> None:
        # пересчитать расписание без перезапуска

    async def stop(self) -> None: ...

    def next_runs(self, limit: int = 10) -> list[dict]: ...
    # [{"workflow": "MyAlertCheck", "at": "2024-01-15T10:30:00Z"}, ...]
```

APScheduler внутри. При срабатывании — вызывает `job_manager.enqueue(name, context={}, triggered_by="scheduler")`.

## JobManager (core/job_manager.py)

Центральный координатор. Единственный кто создаёт и меняет статусы jobs.

```python
class JobManager:
    async def enqueue(
        self,
        workflow_name: str,
        context: dict,
        triggered_by: str
    ) -> WorkflowJob:
        meta = self._get_meta(workflow_name)    # из WorkflowRegistry

        # 1. проверить enabled
        if not meta.enabled:
            raise WorkflowDisabledError(workflow_name)

        # 2. проверить concurrency policy
        await self._check_concurrency(meta)

        # 3. создать job
        job = WorkflowJob(
            id=str(uuid4()),
            workflow_name=workflow_name,
            workflow_type=meta.type,
            triggered_by=triggered_by,
            context=context,
            log_path=self._make_log_path(workflow_name, job_id),
            timeout=meta.timeout,
        )

        # 4. сохранить и поставить в очередь
        await self.job_store.save(job)
        await self.queue.push(job)
        return job

    async def cancel(self, job_id: str) -> WorkflowJob:
        job = await self.job_store.get(job_id)
        if job.status == JobStatus.RUNNING and job.pid:
            os.kill(job.pid, signal.SIGTERM)
        if job.status == JobStatus.PENDING:
            # нет смысла искать в очереди — просто помечаем
            pass
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(UTC)
        await self.job_store.save(job)
        return job

    async def _check_concurrency(self, meta: WorkflowMeta) -> None:
        if meta.concurrency == ConcurrencyPolicy.FORBID:
            running = await self.job_store.count_by_status(
                meta.name, [JobStatus.RUNNING, JobStatus.PENDING]
            )
            if running > 0:
                raise JobAlreadyRunningError(meta.name)
        # QUEUE и ALLOW — не блокируем
```

## Git Manager (core/git_manager.py)

Тонкая обёртка над системным git через asyncio.create_subprocess_exec.

```python
class GitManager:
    def __init__(self, repo_path: str, author_name: str, author_email: str): ...

    async def commit(self, filepath: str, message: str) -> str:
        # git add filepath && git commit -m message
        # возвращает короткий hash коммита

    async def history(self, filepath: str, limit: int = 20) -> list[GitCommit]:
        # git log --follow -n limit -- filepath
        # возвращает [GitCommit(hash, message, author, timestamp), ...]

    async def get_content(self, filepath: str, commit: str) -> str:
        # git show commit:filepath

    async def diff(self, filepath: str, commit_a: str, commit_b: str) -> str:
        # git diff commit_a commit_b -- filepath

    async def restore(self, filepath: str, commit: str) -> None:
        # git checkout commit -- filepath
        # затем commit("restore to {commit}")
```

Инициализация репозитория при старте если `.git` не существует — `git init && git add . && git commit`.

## API роуты

### /workflows

```
GET    /workflows                    список всех workflows с метаданными и статусом enabled
GET    /workflows/{name}             метаданные конкретного workflow
POST   /workflows/{name}/enable      включить workflow
POST   /workflows/{name}/disable     выключить workflow
POST   /scheduler/reload             перечитать workflows и пересоздать расписание
```

### /files

```
GET    /files                        дерево файлов (workflows/, connectors/, actions/)
GET    /files/{path:path}            содержимое файла (text/plain)
PUT    /files/{path:path}            сохранить содержимое → автоматический git commit
POST   /files/upload                 загрузить файл (multipart/form-data)
DELETE /files/{path:path}            удалить файл → git commit
GET    /files/{path:path}/history    список коммитов файла
GET    /files/{path:path}/history/{commit}   содержимое на момент коммита
POST   /files/{path:path}/restore/{commit}   откатить к коммиту → новый коммит
```

### /jobs

```
POST   /jobs                         запустить workflow
       body: {"workflow_name": str, "context": dict}
       → 202 + WorkflowJob

GET    /jobs                         список jobs
       ?workflow_name=&status=&triggered_by=&limit=50&offset=0

GET    /jobs/{job_id}                статус и результат job
POST   /jobs/{job_id}/cancel         отменить / kill
```

### /webhooks

```
POST   /webhooks/{workflow_name}
       Header: X-Webhook-Token: <token>
       body: любой JSON payload
       → 202 + job_id   если токен верный
       → 403            если токен неверный
       → 404            если workflow не найден или не WebhookWorkflow
       → 409            если disabled
```

Токен берётся из `WorkflowMeta.token`. Сравнение через `secrets.compare_digest`.

### /logs

```
GET    /logs/{job_id}                полный лог файла (text/plain)
GET    /logs/{job_id}/stream         SSE стрим, работает пока job RUNNING/PENDING
```

SSE стрим — читать файл построчно, слать каждую строку как event, завершить когда статус job не PENDING и не RUNNING.

### /status

```
GET    /status

{
  "workers":   {"total": 4, "busy": 2, "idle": 2},
  "queue":     {"backend": "memory", "pending": 3},
  "jobs":      {"running": 2, "completed_today": 47, "failed_today": 1, "timeout_today": 0},
  "scheduler": {"next_runs": [{"workflow": "...", "at": "..."}]}
}
```

## Lifespan (main.py)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # старт
    config = load_config("config.yaml")
    setup_logging(config.logging)

    queue     = create_queue(config)
    job_store = JobStore(config)
    runner    = SubprocessRunner(config)
    git       = GitManager(config.git)

    job_manager = JobManager(queue, job_store, runner, config)
    pool        = WorkerPool(config.workers.count, queue, runner, job_store, config)
    scheduler   = OrchestratorScheduler(job_manager)

    # прокидываем в app.state — роуты берут отсюда
    app.state.job_manager = job_manager
    app.state.pool        = pool
    app.state.scheduler   = scheduler
    app.state.git         = git
    app.state.config      = config

    workflows = load_workflow_metas(config)
    await pool.start()
    await scheduler.start(workflows)

    yield

    # стоп
    await scheduler.stop()
    await pool.stop()          # graceful: дождаться текущих jobs или kill по таймауту
    connectors.shutdown()
```

## orchestrator_state.yaml

Хранит enable/disable состояние workflows. Не в git. Создаётся автоматически при первом запуске.

```yaml
workflows:
  alert_check:      enabled
  investigate_host: enabled
  siem_webhook:     disabled
```

При `POST /workflows/{name}/enable` или `/disable` — перезаписывается этот файл + вызывается `scheduler.reload()`.

## Dockerfile

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# инициализация git если нужно — в entrypoint или lifespan
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Чего НЕ делать

- Не реализовывать авторизацию — сервис доверяет локальной Docker-сети
- Не хранить jobs в файле или БД в v1 — только in-memory JobStore
- Не запускать workflows внутри процесса оркестратора — только через SubprocessRunner
- Не писать бизнес-логику в API роутах — только вызовы JobManager / GitManager
- Не обращаться к очереди напрямую из роутов — только через JobManager.enqueue()
- Не создавать отдельные очереди для разных типов workflows — одна общая очередь
- Не хардкодить пути — всё через config
- Не коммитить orchestrator_state.yaml в git — только config.yaml и код
