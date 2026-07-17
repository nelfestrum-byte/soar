from orchestrator.store.base import AbstractJobStore
from orchestrator.store.job_store import InMemoryJobStore, JobStore


def test_in_memory_job_store_satisfies_abstract_job_store():
    store = InMemoryJobStore()
    assert isinstance(store, AbstractJobStore)


def test_job_store_alias_points_to_in_memory_job_store():
    assert JobStore is InMemoryJobStore
