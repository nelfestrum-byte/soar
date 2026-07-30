import os

from soar.tools.watermark import SeenStore, WatermarkStore, seen_store, watermark_store


def test_watermark_store_direct_instantiation_unaffected(tmp_path):
    ws = WatermarkStore(path=str(tmp_path / "wm.json"))
    ws.set("key1", "2026-01-01T00:00:00Z")
    assert ws.get("key1") == "2026-01-01T00:00:00Z"


def test_seen_store_direct_instantiation_unaffected(tmp_path):
    ss = SeenStore(path=str(tmp_path / "seen.json"), ttl=10)
    assert ss.is_seen("x") is False
    ss.mark("x")
    assert ss.is_seen("x") is True


def test_watermark_store_factory_computes_path_from_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"soar:\n  state_dir: {tmp_path / 'state'}\n", encoding="utf-8")
    monkeypatch.setenv("SOAR_CONFIG", str(config_file))

    store = watermark_store("my_workflow")
    assert isinstance(store, WatermarkStore)
    store.set("k", "v")
    assert store.get("k") == "v"
    assert os.path.dirname(store.path) == str(tmp_path / "state")
    assert "my_workflow" in os.path.basename(store.path)


def test_seen_store_factory_computes_path_from_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"soar:\n  state_dir: {tmp_path / 'state'}\n", encoding="utf-8")
    monkeypatch.setenv("SOAR_CONFIG", str(config_file))

    store = seen_store("my_workflow", ttl=3600)
    assert isinstance(store, SeenStore)
    assert store.ttl == 3600
    assert os.path.dirname(store.path) == str(tmp_path / "state")
    assert "my_workflow" in os.path.basename(store.path)


def test_watermark_store_factory_different_names_different_paths(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"soar:\n  state_dir: {tmp_path / 'state'}\n", encoding="utf-8")
    monkeypatch.setenv("SOAR_CONFIG", str(config_file))

    a = watermark_store("wf_a")
    b = watermark_store("wf_b")
    assert a.path != b.path


def test_watermark_store_factory_falls_back_to_default_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SOAR_CONFIG", str(tmp_path / "does_not_exist.yaml"))
    store = watermark_store("wf")
    assert isinstance(store, WatermarkStore)
    assert store.path  # some default path was chosen, no crash
