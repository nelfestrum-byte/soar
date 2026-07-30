import re
from pathlib import Path

REQUIREMENTS_PATH = Path(__file__).resolve().parent.parent.parent / "soar" / "requirements.txt"


def _requirements_names() -> set[str]:
    names = set()
    for line in REQUIREMENTS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if m:
            names.add(m.group(1).lower())
    return names


def test_contract_is_nonempty_dict():
    from soar.runtime_contract import CONTRACT
    assert isinstance(CONTRACT, dict)
    assert len(CONTRACT) > 0


def test_contract_entries_have_import_names_and_kind():
    from soar.runtime_contract import CONTRACT
    for _dist_name, entry in CONTRACT.items():
        assert isinstance(entry.get("import_names"), list)
        assert len(entry["import_names"]) > 0
        assert all(isinstance(n, str) and n for n in entry["import_names"])
        assert entry.get("kind") in {"protocol", "vendor"}


def test_contract_keys_are_in_requirements_txt():
    from soar.runtime_contract import CONTRACT
    req_names = _requirements_names()
    for dist_name in CONTRACT:
        assert dist_name.lower() in req_names, (
            f"CONTRACT key {dist_name!r} not found in soar/requirements.txt"
        )


def test_requirements_txt_lines_are_all_in_contract():
    from soar.runtime_contract import CONTRACT
    contract_keys = {k.lower() for k in CONTRACT}
    req_names = _requirements_names()
    for name in req_names:
        assert name in contract_keys, (
            f"soar/requirements.txt package {name!r} has no CONTRACT entry"
        )


def test_runtime_version_is_string():
    from soar.runtime_contract import RUNTIME_VERSION
    assert isinstance(RUNTIME_VERSION, str)
    assert RUNTIME_VERSION
