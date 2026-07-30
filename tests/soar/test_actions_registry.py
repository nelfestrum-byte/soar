from soar.actions import ActionsRegistry


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_two_public_functions_in_one_file_both_registered(tmp_path):
    _write(
        tmp_path / "multi.py",
        "def enrich_ip(ip):\n    return ip\n\n\ndef enrich_domain(domain):\n    return domain\n",
    )
    reg = ActionsRegistry()
    reg.init(external_dir=str(tmp_path))
    assert "enrich_ip" in reg.list()
    assert "enrich_domain" in reg.list()
    assert reg.enrich_ip("1.2.3.4") == "1.2.3.4"
    assert reg.enrich_domain("x.com") == "x.com"


def test_private_function_not_registered(tmp_path):
    _write(
        tmp_path / "priv.py",
        "def _helper():\n    return 1\n\n\ndef public_one():\n    return 2\n",
    )
    reg = ActionsRegistry()
    reg.init(external_dir=str(tmp_path))
    assert "_helper" not in reg.list()
    assert "public_one" in reg.list()


def test_function_imported_from_other_module_not_registered(tmp_path):
    _write(
        tmp_path / "importer.py",
        "from os.path import join\n\n\ndef local_one():\n    return 1\n",
    )
    reg = ActionsRegistry()
    reg.init(external_dir=str(tmp_path))
    assert "join" not in reg.list()
    assert "local_one" in reg.list()


def test_collision_between_files_last_wins_with_warning(tmp_path, capsys):
    _write(tmp_path / "a_file.py", "def shared():\n    return 'a'\n")
    _write(tmp_path / "b_file.py", "def shared():\n    return 'b'\n")

    reg = ActionsRegistry()
    reg.init(external_dir=str(tmp_path))
    # last-wins: b_file.py sorts after a_file.py alphabetically
    assert reg.shared() == "b"
