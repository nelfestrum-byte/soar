from orchestrator.config import OrchestratorConfig, load_config


def test_load_config_default():
    config = OrchestratorConfig()
    assert config.workers.count == 4
    assert config.workers.default_timeout == 300
    assert config.queue.backend == "memory"
    assert config.logging.level == "INFO"


def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
workers:
  count: 2
  default_timeout: 600
queue:
  backend: redis
  redis_url: redis://localhost:6379/1
""")
    config = load_config(str(config_file))
    assert config.workers.count == 2
    assert config.workers.default_timeout == 600
    assert config.queue.backend == "redis"


def test_load_config_nonexistent():
    config = load_config("nonexistent.yaml")
    assert config.workers.count == 4
