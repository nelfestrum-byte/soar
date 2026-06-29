# SOAR Module

Ты пишешь независимый Python-модуль для построения SOAR-сценариев.
Модуль встраивается в надпроект как пакет. Никакого планировщика, HTTP-сервера и UI внутри модуля — вся оркестрация в надпроекте.

## Стек

- Python 3.11+
- loguru — логирование
- pyyaml — конфиги коннекторов
- зависимости конкретных коннекторов (elasticsearch, vt-py и т.д.) — отдельно в каждом коннекторе

## Структура проекта

```
soar/
├── logger.py                        # модуль логирования
├── connectors/
│   ├── __init__.py                  # ConnectorRegistry → объект connectors
│   ├── base.py                      # BaseConnector
│   ├── elastic/
│   │   ├── elastic.py               # ElasticConnector(BaseConnector)
│   │   ├── elastic.example.yml      # в репозиторий
│   │   └── elastic.yml              # .gitignore
│   └── virus_total/
│       ├── virus_total.py
│       ├── virus_total.example.yml
│       └── virus_total.yml
├── actions/
│   ├── __init__.py                  # ActionsRegistry → объект actions
│   └── send_tg_soc_team.py          # пример action
├── workflows/
│   ├── __init__.py                  # WorkflowRegistry → объект workflows
│   ├── base.py                      # BaseWorkflow, ScheduledWorkflow, WebhookWorkflow, ManualWorkflow, WorkflowResult
│   └── alert_check.py               # пример workflow
└── examples/
    └── nadproject_integration.py    # ОБЯЗАТЕЛЕН: примеры вызова из надпроекта
```

## Модуль logger.py

Единственный публичный интерфейс — две функции:

```python
def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Вызывается один раз из надпроекта при старте. Без вызова — stderr с дефолтами."""

def get_logger(name: str) -> Logger:
    """Соглашение об именах: connector.<instance>, workflow.<ClassName>, action.<name>"""
```

Формат: `{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}`

## Модуль connectors/

### Конфиг

Каждый коннектор хранит свой YAML рядом с реализацией. Реальные `*.yml` — в `.gitignore`.

```yaml
# elastic.example.yml — эталон структуры
instances:
  elastic1:
    host: 10.0.0.1
    port: 9200
    api_key: YOUR_KEY
  elastic_backup:
    host: 10.0.0.2
    port: 9200
    api_key: YOUR_KEY
```

### BaseConnector

```python
class BaseConnector:
    def __init__(self, instance_name: str, **params): ...
    # зашито: self.instance_name, self._connected = False, self._logger

    def _connect_impl(self) -> None:
        raise NotImplementedError  # переопределяется в дочернем классе

    def _ensure_connected(self) -> None:
        # вызывается в начале каждого публичного метода дочернего класса
        # если не подключён — вызывает _connect_impl(), логирует

    def disconnect(self) -> None:
        raise NotImplementedError  # переопределяется, вызывается реестром при shutdown
```

### Реализация коннектора (паттерн)

```python
class ElasticConnector(BaseConnector):
    def __init__(self, instance_name: str, host: str, port: int, api_key: str):
        super().__init__(instance_name)
        # сохранить params как атрибуты

    def _connect_impl(self): ...   # создать self._client

    def disconnect(self): ...      # закрыть self._client, self._connected = False

    def query(self, index: str, dsl: dict) -> list[dict]:
        self._ensure_connected()   # всегда первой строкой в публичных методах
        ...
```

### ConnectorRegistry (`connectors/__init__.py`)

- При старте читает все `*.yml` (не `*.example.yml`) из подпапок `connectors/`
- По ключу `type` в YAML находит класс коннектора
- Создаёт экземпляры, регистрирует как атрибуты объекта `connectors`
- Подключение lazy — при первом вызове метода

```python
from soar.connectors import connectors

connectors.elastic1          # ElasticConnector
connectors.elastic_backup    # ElasticConnector
connectors.list()            # [{'name': 'elastic1', 'type': 'elastic', 'connected': False}, ...]
connectors.shutdown()        # disconnect() на всех, вызывается надпроектом при остановке
```

## Модуль actions/

DRY-сниппеты под конкретный прод. Пишутся в WEB IDE. Работают с конкретными экземплярами коннекторов напрямую — никакой параметризации коннектора.

### Соглашение

- Один файл — один callable
- Имя файла = имя функции (или класс с `__call__`)
- Базового класса нет, форма свободная
- Логирование опционально

```python
# actions/send_tg_soc_team.py
from soar.connectors import connectors

def send_tg_soc_team(message: str) -> None:
    connectors.telegram_main.send(chat_id="-100123456789", text=message)
```

### ActionsRegistry (`actions/__init__.py`)

- Импортирует все `*.py` из папки `actions/`
- Ищет callable с именем совпадающим с именем файла
- Регистрирует как атрибут объекта `actions`

```python
from soar.actions import actions

actions.send_tg_soc_team(message="alert!")
actions.list()   # ['send_tg_soc_team', 'enrich_ip_virustotal', ...]
```

## Модуль workflows/

### WorkflowResult (dataclass)

```python
@dataclass
class WorkflowResult:
    success: bool
    workflow_name: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    error: Exception | None = None
    data: dict | None = None
```

### Иерархия

```
BaseWorkflow
├── ScheduledWorkflow   # атрибуты: schedule: str (cron) | interval: int (секунды)
├── WebhookWorkflow     # атрибуты: path: str, token: str
└── ManualWorkflow      # маркерный класс, без доп. атрибутов
```

### BaseWorkflow

```python
class BaseWorkflow:
    def run(self, context: dict) -> dict | None:
        raise NotImplementedError  # переопределяется разработчиком

    def execute(self, context: dict | None = None) -> WorkflowResult:
        # НЕ переопределяется — точка входа для надпроекта
        # оборачивает run(): логирование старта/финиша, таймер, перехват исключений
        ...
```

### Примеры workflows (паттерн)

```python
# ScheduledWorkflow
class MyAlertCheck(ScheduledWorkflow):
    schedule = "*/10 * * * *"

    def run(self, context):
        alerts = connectors.elastic1.query("alerts", {"query": {"match_all": {}}})
        for alert in alerts:
            result = actions.enrich_ip_virustotal(ip=alert['_source']['src_ip'])
            actions.send_tg_soc_team(message=str(alert['_source']))

# WebhookWorkflow
class SIEMAlert(WebhookWorkflow):
    path = "/siem/alert"
    token = "secret"

    def run(self, context):
        alert = context['payload']   # тело входящего HTTP-запроса
        actions.send_tg_soc_team(message=alert['title'])

# ManualWorkflow
class InvestigateHost(ManualWorkflow):
    def run(self, context):
        result = actions.enrich_ip_virustotal(ip=context['ip'])
        return {'result': result}    # попадает в WorkflowResult.data
```

### WorkflowRegistry (`workflows/__init__.py`)

- Импортирует все `*.py` из папки `workflows/` (кроме `base.py`)
- Находит все классы — наследники `BaseWorkflow`
- Регистрирует по имени класса

```python
from soar.workflows import workflows

workflows.list()
# [
#   {'name': 'MyAlertCheck',   'type': 'scheduled', 'schedule': '*/10 * * * *'},
#   {'name': 'SIEMAlert',      'type': 'webhook',   'path': '/siem/alert', 'token': '...'},
#   {'name': 'InvestigateHost','type': 'manual'},
# ]

workflows.get('MyAlertCheck') -> dict
workflows.execute('MyAlertCheck', context={}) -> WorkflowResult
```

## Граница ответственности: SOAR ↔ надпроект

| Зона | SOAR модуль | Надпроект |
|------|-------------|-----------|
| Конфиги | читает `*.yml` при старте | хранит, бэкапит, деплоит на прод |
| Коннекторы | lazy connect, disconnect | — |
| Actions | авто-импорт, реестр | пишет в WEB IDE |
| Workflows | `execute()`, `WorkflowResult` | планировщик, HTTP-сервер, хранение результатов |
| Webhook-маршруты | `path`, `token` как метаданные | регистрирует маршруты, валидирует токен |
| Логирование | базовые события в base-классах | вызывает `setup_logging()`, задаёт level и путь |
| Shutdown | `connectors.shutdown()` | вызывает при остановке |

## examples/nadproject_integration.py — ОБЯЗАТЕЛЕН

Файл должен содержать рабочие примеры для всех сценариев интеграции:

1. **Инициализация** — `setup_logging()`, импорт реестров
2. **Чтение метаданных** — `workflows.list()`, фильтрация по типу для регистрации webhook-маршрутов
3. **Запуск scheduled workflow** — вызов `execute()`, обработка `WorkflowResult`
4. **Обработка входящего webhook** — передача `context['payload']`, возврат статуса
5. **Ручной запуск с параметрами** — передача `context`, чтение `result.data`
6. **Graceful shutdown** — `atexit.register(connectors.shutdown)`

## Чего НЕ делать

- Не добавлять планировщик внутрь модуля
- Не поднимать HTTP-сервер внутрь модуля
- Не создавать единую схему данных между коннекторами
- Не хардкодить креды — только через `*.yml`
- Не класть реальные `*.yml` в репозиторий — только `*.example.yml`
- Не переопределять `execute()` в workflow — только `run()`
- Не обращаться к коннектору без `_ensure_connected()` в начале метода
