import pytest

from orchestrator.config import OrchestratorConfig
from orchestrator.core.queue.memory import InMemoryQueue
from orchestrator.core.queue.sql_queue import SQLQueue
from orchestrator.db.session import init_engine
from orchestrator.main import create_job_store, create_queue
from orchestrator.store.job_store import InMemoryJobStore
from orchestrator.store.sql_job_store import SQLJobStore


def test_create_job_store_defaults_to_in_memory():
    config = OrchestratorConfig()
    store = create_job_store(config)
    assert isinstance(store, InMemoryJobStore)


def test_create_job_store_sql_when_configured():
    init_engine("sqlite+aiosqlite:///:memory:")
    config = OrchestratorConfig()
    config.jobs.persistence = "sql"
    store = create_job_store(config)
    assert isinstance(store, SQLJobStore)


def test_create_queue_defaults_to_in_memory():
    config = OrchestratorConfig()
    queue = create_queue(config)
    assert isinstance(queue, InMemoryQueue)


def test_create_queue_sql_requires_sql_persistence_raises():
    config = OrchestratorConfig()
    config.queue.backend = "sql"
    config.jobs.persistence = "memory"

    with pytest.raises(ValueError, match="jobs.persistence"):
        create_queue(config)


def test_create_queue_sql_with_sql_persistence_ok():
    init_engine("sqlite+aiosqlite:///:memory:")
    config = OrchestratorConfig()
    config.queue.backend = "sql"
    config.jobs.persistence = "sql"

    queue = create_queue(config)
    assert isinstance(queue, SQLQueue)
