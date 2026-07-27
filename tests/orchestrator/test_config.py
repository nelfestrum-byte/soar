import pytest
from pydantic import ValidationError

from orchestrator.config import DatabaseConfig, HttpClientConfig, OrchestratorConfig, load_config


def test_load_config_default():
    config = OrchestratorConfig()
    assert config.workers.count == 4
    assert config.workers.default_timeout == 300
    assert config.queue.backend == "memory"
    assert config.logging.level == "INFO"
    assert config.database.table_prefix == ""
    assert config.jobs.persistence == "memory"
    assert config.http_client.cache_backend == "memory"
    assert config.http_client.default_ttl == 3600
    assert config.http_client.domain_ttl == {}


def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
workers:
  count: 2
  default_timeout: 600
queue:
  backend: redis
  redis_url: redis://localhost:6379/1
database:
  url: postgresql+asyncpg://soar:soar@localhost:5432/soar
  table_prefix: "stage_"
jobs:
  persistence: sql
http_client:
  cache_backend: redis
  default_ttl: 7200
  domain_ttl:
    api.virustotal.com: 86400
""")
    config = load_config(str(config_file))
    assert config.workers.count == 2
    assert config.workers.default_timeout == 600
    assert config.queue.backend == "redis"
    assert config.database.url == "postgresql+asyncpg://soar:soar@localhost:5432/soar"
    assert config.database.table_prefix == "stage_"
    assert config.jobs.persistence == "sql"
    assert config.http_client.cache_backend == "redis"
    assert config.http_client.default_ttl == 7200
    assert config.http_client.domain_ttl == {"api.virustotal.com": 86400}


def test_load_config_nonexistent():
    config = load_config("nonexistent.yaml")
    assert config.workers.count == 4


def test_database_table_prefix_rejects_invalid_characters():
    with pytest.raises(ValidationError):
        DatabaseConfig(table_prefix="bad-prefix")

    with pytest.raises(ValidationError):
        DatabaseConfig(table_prefix="bad prefix")


def test_database_table_prefix_accepts_valid_characters():
    cfg = DatabaseConfig(table_prefix="stage_v2_")
    assert cfg.table_prefix == "stage_v2_"


def test_http_client_config_defaults():
    cfg = HttpClientConfig()
    assert cfg.cache_backend == "memory"
    assert cfg.default_ttl == 3600
    assert cfg.domain_ttl == {}
