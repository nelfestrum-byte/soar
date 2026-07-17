from orchestrator.config import OrchestratorConfig
from orchestrator.db.session import init_engine
from orchestrator.main import create_job_store
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
