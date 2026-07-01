# Redis Queue Backend Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/redis-queue-backend.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a production-ready Redis queue backend for distributed SOAR deployments with connection pooling, error handling, and comprehensive testing.

**Architecture:** Extend existing `RedisQueue` class with aioredis connection pooling and auto-reconnect. Add Docker Redis service. Maintain backward compatibility with `InMemoryQueue` for single-instance deployments.

**Tech Stack:** Python 3.11+, aioredis, Docker Compose, pytest, loguru

## Global Constraints

- Python 3.11+ required
- aioredis for async Redis operations
- pytest + pytest-asyncio for testing
- loguru for logging
- Docker Compose for deployment
- Maintain backward compatibility with InMemoryQueue

---

## File Structure

| File | Purpose |
|------|---------|
| `orchestrator/core/queue/redis_queue.py` | Enhanced RedisQueue with connection pooling and error handling |
| `orchestrator/config.py` | Add Redis-specific config options |
| `deploy/stage/docker-compose.yml` | Add Redis service |
| `tests/orchestrator/test_redis_queue.py` | Unit tests for RedisQueue |
| `tests/orchestrator/test_redis_integration.py` | Integration tests with real Redis |
| `orchestrator/api/status.py` | Add Redis health check |

---

### Task 1: Enhance RedisQueue Implementation

**Covers:** [S4]

**Files:**
- Modify: `orchestrator/core/queue/redis_queue.py`
- Test: `tests/orchestrator/test_redis_queue.py`

**Interfaces:**
- Consumes: `AbstractJobQueue` base class, `WorkflowJob` model
- Produces: Enhanced `RedisQueue` with `push()`, `pop()`, `size()`, `clear()` methods

- [ ] **Step 1: Write the failing test for connection pooling**

```python
# tests/orchestrator/test_redis_queue.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_redis_queue_push_with_pool():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_pool = AsyncMock()
        mock_redis.ConnectionPool.return_value = mock_pool
        mock_redis.Redis.return_value = AsyncMock()
        
        queue = RedisQueue("redis://localhost:6379/0", max_connections=10)
        job = WorkflowJob(workflow_name="test")
        
        await queue.push(job)
        
        mock_redis.ConnectionPool.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=10,
            decode_responses=True
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_redis_queue.py::test_redis_queue_push_with_pool -v`
Expected: FAIL with "RedisQueue() got an unexpected keyword argument 'max_connections'"

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/core/queue/redis_queue.py
import json
from typing import Optional

from redis import asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError

from orchestrator.core.queue.base import AbstractJobQueue
from orchestrator.models.job import WorkflowJob
from loguru import logger


class RedisQueue(AbstractJobQueue):
    def __init__(
        self,
        redis_url: str,
        max_connections: int = 10,
        push_timeout: float = 5.0,
        pop_timeout: float = 1.0,
    ):
        self._redis_url = redis_url
        self._max_connections = max_connections
        self._push_timeout = push_timeout
        self._pop_timeout = pop_timeout
        self._key = "soar:jobs"
        self._pool: Optional[aioredis.ConnectionPool] = None
        self._redis: Optional[aioredis.Redis] = None
        self._connect()

    def _connect(self):
        self._pool = aioredis.ConnectionPool(
            self._redis_url,
            max_connections=self._max_connections,
            decode_responses=True,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)

    async def _ensure_connected(self):
        if self._redis is None:
            self._connect()

    async def push(self, job: WorkflowJob) -> None:
        await self._ensure_connected()
        data = json.dumps({
            "id": job.id,
            "workflow_name": job.workflow_name,
            "workflow_type": job.workflow_type,
            "triggered_by": job.triggered_by,
            "context": job.context,
            "log_path": job.log_path,
            "timeout": job.timeout,
        })
        try:
            await self._redis.lpush(self._key, data)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis push failed: {e}")
            self._connect()
            await self._redis.lpush(self._key, data)

    async def pop(self, timeout: float = 1.0) -> Optional[WorkflowJob]:
        await self._ensure_connected()
        try:
            result = await self._redis.brpop(self._key, timeout=timeout)
            if result is None:
                return None
            _, data = result
            item = json.loads(data)
            return WorkflowJob(
                id=item["id"],
                workflow_name=item["workflow_name"],
                workflow_type=item["workflow_type"],
                triggered_by=item["triggered_by"],
                context=item["context"],
                log_path=item.get("log_path"),
                timeout=item.get("timeout"),
            )
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis pop failed: {e}")
            self._connect()
            return None

    async def size(self) -> int:
        await self._ensure_connected()
        try:
            return await self._redis.llen(self._key)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis size failed: {e}")
            return 0

    async def clear(self) -> None:
        await self._ensure_connected()
        try:
            await self._redis.delete(self._key)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis clear failed: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/orchestrator/test_redis_queue.py::test_redis_queue_push_with_pool -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/core/queue/redis_queue.py tests/orchestrator/test_redis_queue.py
git commit -m "feat: enhance RedisQueue with connection pooling and error handling"
```

---

### Task 2: Add Redis Health Check to Status Endpoint

**Covers:** [S8]

**Files:**
- Modify: `orchestrator/api/status.py`
- Test: `tests/orchestrator/api/test_status.py`

**Interfaces:**
- Consumes: `RedisQueue` from Task 1
- Produces: Enhanced `/status` endpoint with Redis connectivity info

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/api/test_status.py
import pytest
from httpx import AsyncClient, ASGITransport
from orchestrator.main import app
from orchestrator.core.queue.redis_queue import RedisQueue


@pytest.mark.asyncio
async def test_status_redis_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert "queue" in data
        assert "backend" in data["queue"]
        assert "connected" in data["queue"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/api/test_status.py::test_status_redis_health -v`
Expected: FAIL with "KeyError: 'connected'"

- [ ] **Step 3: Write minimal implementation**

```python
# orchestrator/api/status.py
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    config = request.app.state.config
    pool = request.app.state.pool
    queue = request.app.state.queue
    
    queue_info = {
        "backend": config.queue.backend,
        "size": await queue.size(),
    }
    
    if config.queue.backend == "redis":
        try:
            await queue._ensure_connected()
            await queue._redis.ping()
            queue_info["connected"] = True
        except Exception:
            queue_info["connected"] = False
    
    return {
        "workers": pool.count,
        "queue": queue_info,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/orchestrator/api/test_status.py::test_status_redis_health -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/api/status.py tests/orchestrator/api/test_status.py
git commit -m "feat: add Redis health check to status endpoint"
```

---

### Task 3: Update Docker Compose with Redis Service

**Covers:** [S5]

**Files:**
- Modify: `deploy/stage/docker-compose.yml`

**Interfaces:**
- Consumes: None
- Produces: Docker Compose configuration with Redis service

- [ ] **Step 1: Update docker-compose.yml**

```yaml
# deploy/stage/docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    container_name: soar-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  orchestrator:
    build:
      context: ../..
      dockerfile: deploy/stage/Dockerfile.orchestrator
    container_name: soar-orchestrator
    expose:
      - "8000"
    volumes:
      - soar-data:/app/data
      - soar-logs:/var/log/soar
    environment:
      - SOAR_CONFIG=/app/data/config.yaml
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/status')"]
      interval: 10s
      timeout: 5s
      retries: 3

  ui:
    build:
      context: ../..
      dockerfile: deploy/stage/Dockerfile.ui
    container_name: soar-ui
    ports:
      - "3000:80"
    depends_on:
      orchestrator:
        condition: service_healthy
    restart: unless-stopped

volumes:
  soar-data:
  soar-logs:
  redis-data:
```

- [ ] **Step 2: Verify Docker Compose syntax**

Run: `cd deploy/stage && docker compose config`
Expected: Valid YAML output with all services

- [ ] **Step 3: Commit**

```bash
git add deploy/stage/docker-compose.yml
git commit -m "feat: add Redis service to Docker Compose"
```

---

### Task 4: Update Configuration for Redis

**Covers:** [S6]

**Files:**
- Modify: `orchestrator/config.py`
- Modify: `deploy/stage/config.yaml`

**Interfaces:**
- Consumes: None
- Produces: Enhanced `QueueConfig` with Redis-specific options

- [ ] **Step 1: Update QueueConfig**

```python
# orchestrator/config.py
from pydantic import BaseModel


class QueueConfig(BaseModel):
    backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 10
    redis_push_timeout: float = 5.0
    redis_pop_timeout: float = 1.0
```

- [ ] **Step 2: Update create_queue function**

```python
# orchestrator/main.py
def create_queue(config):
    if config.queue.backend == "redis":
        return RedisQueue(
            config.queue.redis_url,
            max_connections=config.queue.redis_max_connections,
            push_timeout=config.queue.redis_push_timeout,
            pop_timeout=config.queue.redis_pop_timeout,
        )
    return InMemoryQueue()
```

- [ ] **Step 3: Update stage config.yaml**

```yaml
# deploy/stage/config.yaml
queue:
  backend: redis
  redis_url: redis://redis:6379/0
  redis_max_connections: 10
  redis_push_timeout: 5.0
  redis_pop_timeout: 1.0
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/config.py orchestrator/main.py deploy/stage/config.yaml
git commit -m "feat: add Redis-specific configuration options"
```

---

### Task 5: Write Unit Tests for RedisQueue

**Covers:** [S7]

**Files:**
- Create: `tests/orchestrator/test_redis_queue.py`

**Interfaces:**
- Consumes: Enhanced `RedisQueue` from Task 1
- Produces: Comprehensive unit tests

- [ ] **Step 1: Write push/pop tests**

```python
# tests/orchestrator/test_redis_queue.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_redis_queue_push_success():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        
        queue = RedisQueue("redis://localhost:6379/0")
        job = WorkflowJob(workflow_name="test")
        
        await queue.push(job)
        
        queue._redis.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_redis_queue_pop_success():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        mock_redis.Redis.return_value.brpop = AsyncMock(return_value=(
            b"soar:jobs",
            b'{"id": "123", "workflow_name": "test", "workflow_type": "manual", "triggered_by": "api", "context": {}}'
        ))
        
        queue = RedisQueue("redis://localhost:6379/0")
        job = await queue.pop()
        
        assert job is not None
        assert job.workflow_name == "test"


@pytest.mark.asyncio
async def test_redis_queue_pop_empty():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        mock_redis.Redis.return_value.brpop = AsyncMock(return_value=None)
        
        queue = RedisQueue("redis://localhost:6379/0")
        job = await queue.pop()
        
        assert job is None


@pytest.mark.asyncio
async def test_redis_queue_size():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        mock_redis.Redis.return_value.llen = AsyncMock(return_value=5)
        
        queue = RedisQueue("redis://localhost:6379/0")
        size = await queue.size()
        
        assert size == 5


@pytest.mark.asyncio
async def test_redis_queue_clear():
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        mock_redis.Redis.return_value.delete = AsyncMock()
        
        queue = RedisQueue("redis://localhost:6379/0")
        await queue.clear()
        
        queue._redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_redis_queue_push_connection_error():
    from redis.exceptions import ConnectionError
    
    with patch('orchestrator.core.queue.redis_queue.aioredis') as mock_redis:
        mock_redis.ConnectionPool.return_value = MagicMock()
        mock_redis.Redis.return_value = AsyncMock()
        mock_redis.Redis.return_value.lpush = AsyncMock(side_effect=ConnectionError())
        
        queue = RedisQueue("redis://localhost:6379/0")
        job = WorkflowJob(workflow_name="test")
        
        with pytest.raises(ConnectionError):
            await queue.push(job)
        
        assert mock_redis.ConnectionPool.call_count == 2
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/orchestrator/test_redis_queue.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_redis_queue.py
git commit -m "test: add unit tests for RedisQueue"
```

---

### Task 6: Write Integration Tests

**Covers:** [S7]

**Files:**
- Create: `tests/orchestrator/test_redis_integration.py`

**Interfaces:**
- Consumes: Enhanced `RedisQueue` from Task 1
- Produces: Integration tests with real Redis

- [ ] **Step 1: Write integration test**

```python
# tests/orchestrator/test_redis_integration.py
import pytest
import redis.asyncio as aioredis
from orchestrator.core.queue.redis_queue import RedisQueue
from orchestrator.models.job import WorkflowJob


@pytest.fixture
async def redis_queue():
    queue = RedisQueue("redis://localhost:6379/1")
    await queue.clear()
    yield queue
    await queue.clear()


@pytest.mark.asyncio
async def test_redis_integration_push_pop(redis_queue):
    job = WorkflowJob(workflow_name="integration_test")
    await redis_queue.push(job)
    
    assert await redis_queue.size() == 1
    
    popped = await redis_queue.pop(timeout=0.1)
    assert popped is not None
    assert popped.workflow_name == "integration_test"
    assert await redis_queue.size() == 0


@pytest.mark.asyncio
async def test_redis_integration_multiple_jobs(redis_queue):
    for i in range(5):
        await redis_queue.push(WorkflowJob(workflow_name=f"wf_{i}"))
    
    assert await redis_queue.size() == 5
    
    for i in range(5):
        job = await redis_queue.pop(timeout=0.1)
        assert job.workflow_name == f"wf_{i}"


@pytest.mark.asyncio
async def test_redis_integration_clear(redis_queue):
    for i in range(3):
        await redis_queue.push(WorkflowJob(workflow_name=f"wf_{i}"))
    
    assert await redis_queue.size() == 3
    
    await redis_queue.clear()
    assert await redis_queue.size() == 0
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/orchestrator/test_redis_integration.py -v`
Expected: All tests pass (requires running Redis)

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_redis_integration.py
git commit -m "test: add integration tests for RedisQueue"
```

---

### Task 7: Update Documentation

**Covers:** [S9]

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: All previous tasks
- Produces: Updated documentation

- [ ] **Step 1: Update README**

```markdown
## Queue Backend Configuration

SOAR supports two queue backends:

### In-Memory (Default)
```yaml
queue:
  backend: memory
```

### Redis
```yaml
queue:
  backend: redis
  redis_url: redis://redis:6379/0
  redis_max_connections: 10
  redis_push_timeout: 5.0
  redis_pop_timeout: 1.0
```

### Docker Compose with Redis

```bash
cd deploy/stage
docker compose up --build
```

### Health Check

Check Redis connectivity:
```bash
curl http://localhost:8000/status
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Redis queue backend documentation"
```

---

## Success Criteria

- [ ] RedisQueue handles connection errors gracefully
- [ ] Auto-reconnect works with exponential backoff
- [ ] Docker Compose includes Redis service
- [ ] All tests pass (unit + integration)
- [ ] Health check shows Redis status
- [ ] Config supports both memory and redis backends
