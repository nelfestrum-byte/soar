import json
import time

from soar.tools.watermark import SeenStore, WatermarkStore


def test_watermark_first_run_returns_none(tmp_path):
    store = WatermarkStore(str(tmp_path / "wm.json"))
    assert store.get("siem_alerts") is None


def test_watermark_set_get_roundtrip(tmp_path):
    store = WatermarkStore(str(tmp_path / "wm.json"))
    store.set("siem_alerts", "2026-07-05T10:40:00+00:00")
    assert store.get("siem_alerts") == "2026-07-05T10:40:00+00:00"


def test_watermark_survives_restart(tmp_path):
    path = str(tmp_path / "wm.json")
    WatermarkStore(path).set("siem_alerts", "2026-07-05T10:40:00+00:00")
    # new instance, same file — simulates orchestrator restart
    assert WatermarkStore(path).get("siem_alerts") == "2026-07-05T10:40:00+00:00"


def test_watermark_independent_keys(tmp_path):
    store = WatermarkStore(str(tmp_path / "wm.json"))
    store.set("siem_alerts", "2026-07-05T10:00:00+00:00")
    store.set("irp_reconcile", "2026-07-05T11:00:00+00:00")
    assert store.get("siem_alerts") == "2026-07-05T10:00:00+00:00"
    assert store.get("irp_reconcile") == "2026-07-05T11:00:00+00:00"


def test_watermark_corrupt_json_returns_none(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text("{not json", encoding="utf-8")
    store = WatermarkStore(str(path))
    assert store.get("siem_alerts") is None
    # set still works after corruption
    store.set("siem_alerts", "2026-07-05T10:40:00+00:00")
    assert store.get("siem_alerts") == "2026-07-05T10:40:00+00:00"


def test_watermark_write_is_atomic(tmp_path):
    path = tmp_path / "wm.json"
    store = WatermarkStore(str(path))
    store.set("k", "v")
    # no leftover tmp file, file is valid JSON
    assert not (tmp_path / "wm.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}


def test_watermark_creates_parent_dirs(tmp_path):
    store = WatermarkStore(str(tmp_path / "nested" / "dir" / "wm.json"))
    store.set("k", "v")
    assert store.get("k") == "v"


def test_seen_store_mark_and_check(tmp_path):
    store = SeenStore(str(tmp_path / "seen.json"), ttl=3600)
    assert store.is_seen("irp_seen:1") is False
    store.mark("irp_seen:1")
    assert store.is_seen("irp_seen:1") is True
    # persists across instances
    assert SeenStore(str(tmp_path / "seen.json")).is_seen("irp_seen:1") is True


def test_seen_store_ttl_expiry(tmp_path):
    path = str(tmp_path / "seen.json")
    store = SeenStore(path, ttl=3600)
    store.mark("irp_seen:1")
    # rewrite the file with an already-expired entry
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"irp_seen:1": time.time() - 10}, f)
    assert store.is_seen("irp_seen:1") is False


def test_seen_store_corrupt_json(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("[]", encoding="utf-8")
    store = SeenStore(str(path))
    assert store.is_seen("x") is False
    store.mark("x")
    assert store.is_seen("x") is True
