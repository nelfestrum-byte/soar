from unittest.mock import patch

import yaml

from soar.connectors import ConnectorRegistry


def _write_yml(path, instances: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"instances": instances}), encoding="utf-8")


def test_two_instances_same_name_different_types_coexist(tmp_path):
    _write_yml(tmp_path / "file" / "a.yml", {"prod": {"base_path": "/tmp/a"}})
    _write_yml(tmp_path / "urlhaus" / "b.yml", {"prod": {}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    file_prod = reg.get_instance("file", "prod")
    urlhaus_prod = reg.get_instance("urlhaus", "prod")
    assert file_prod is not None
    assert urlhaus_prod is not None
    assert file_prod is not urlhaus_prod
    assert type(file_prod).__name__ == "FileConnector"
    assert type(urlhaus_prod).__name__ == "UrlhausConnector"


def test_collision_within_same_type_last_wins_with_warning(tmp_path):
    _write_yml(tmp_path / "file" / "a.yml", {"dup": {"base_path": "/tmp/a"}})
    _write_yml(tmp_path / "file" / "b.yml", {"dup": {"base_path": "/tmp/b"}})

    reg = ConnectorRegistry()
    with patch("soar.connectors._log") as mock_log:
        reg.init(external_dir=str(tmp_path))

    inst = reg.get_instance("file", "dup")
    assert inst is not None
    # last-wins: b.yml sorts after a.yml
    assert str(inst.base_path).replace("\\", "/").endswith("/tmp/b")
    warnings = [str(c.args[0]) for c in mock_log.warning.call_args_list]
    assert any("Duplicate instance" in w for w in warnings)


def test_discover_external_ignores_class_imported_from_other_module(tmp_path):
    type_a_dir = tmp_path / "type_a"
    type_a_dir.mkdir(parents=True)
    (type_a_dir / "a.py").write_text(
        "from soar.connectors.base import BaseConnector\n"
        "\n"
        "class AaConnector(BaseConnector):\n"
        "    def _connect_impl(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    type_b_dir = tmp_path / "type_b"
    type_b_dir.mkdir(parents=True)
    (type_b_dir / "b.py").write_text(
        "from soar.connectors.file.file import FileConnector\n"
        "from soar.connectors.base import BaseConnector\n"
        "\n"
        "class AaConnector(BaseConnector):\n"
        "    def _connect_impl(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    _write_yml(tmp_path / "type_b" / "b.yml", {"only": {}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    cls = reg._classes.get("type_b")
    assert cls is not None
    # Alphabetically, "AaConnector" < "FileConnector" < "ZzConnector" — a
    # last-wins scan of dir(mod) without the __module__ == fqn check would
    # pick the imported FileConnector instead of the module's own class.
    assert cls.__name__ == "AaConnector"
    assert cls.__module__ == "soar.connectors.type_b.b"


def test_list_form_unchanged_after_namespace_refactor(tmp_path):
    _write_yml(tmp_path / "file" / "a.yml", {"myinst": {"base_path": "/tmp/a"}})

    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))

    items = reg.list()
    assert isinstance(items, list)
    entry = next(i for i in items if i["name"] == "myinst")
    assert set(entry.keys()) == {"name", "type", "connected"}
    assert entry["type"] == "file"
    assert entry["connected"] is False


def test_get_instance_missing_returns_none(tmp_path):
    reg = ConnectorRegistry()
    reg.init(external_dir=str(tmp_path))
    assert reg.get_instance("file", "does_not_exist") is None
    assert reg.get_instance("nonexistent_type", "x") is None
