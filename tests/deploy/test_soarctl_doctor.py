import json
import socket

from deploy.soarctl_lib.doctor import (
    check_disk_space,
    check_docker_compose,
    check_docker_present,
    check_env_file,
    check_git_checkout,
    check_ports_free,
    run_checks,
)


def test_check_docker_present_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    ok, _ = check_docker_present()
    assert ok is True


def test_check_docker_present_false(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, _ = check_docker_present()
    assert ok is False


def test_check_docker_compose_ok(monkeypatch):
    def fake_run(argv, **kw):
        class _R:
            stdout = "Docker Compose version v2.20.0"

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.doctor.run", fake_run)
    ok, _ = check_docker_compose()
    assert ok is True


def test_check_docker_compose_fails(monkeypatch):
    from deploy.soarctl_lib.runner import CommandError

    def fake_run(argv, **kw):
        raise CommandError(argv, 1, "not found")

    monkeypatch.setattr("deploy.soarctl_lib.doctor.run", fake_run)
    ok, message = check_docker_compose()
    assert ok is False
    assert "not found" in message


def test_check_ports_free_reports_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy_port = s.getsockname()[1]
        ok, message = check_ports_free([busy_port])
        assert ok is False
        assert str(busy_port) in message


def test_check_ports_free_reports_ok_for_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    ok, _ = check_ports_free([free_port])
    assert ok is True


def test_check_env_file_missing(tmp_path):
    ok, message = check_env_file(tmp_path)
    assert ok is False
    assert ".env" in message


def test_check_env_file_present(tmp_path):
    (tmp_path / ".env").write_text("AUTH_SECRET_KEY=abc\n")
    ok, _ = check_env_file(tmp_path)
    assert ok is True


def test_check_disk_space_reports_ok(tmp_path):
    ok, _ = check_disk_space(tmp_path, min_free_gb=0)
    assert ok is True


def test_check_disk_space_reports_fail_for_huge_requirement(tmp_path):
    ok, _ = check_disk_space(tmp_path, min_free_gb=10**9)
    assert ok is False


def test_check_git_checkout_absent_when_no_source_json(tmp_path):
    assert check_git_checkout(tmp_path) is None


def test_check_git_checkout_ok_when_present_and_checkout_exists(tmp_path, monkeypatch):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    (tmp_path / "source.json").write_text(json.dumps({"repo": str(checkout), "checkout": str(checkout)}))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git" if name == "git" else None)

    result = check_git_checkout(tmp_path)

    assert result is not None
    ok, _ = result
    assert ok is True


def test_check_git_checkout_fails_when_checkout_missing(tmp_path, monkeypatch):
    missing = tmp_path / "gone"
    (tmp_path / "source.json").write_text(json.dumps({"repo": str(missing), "checkout": str(missing)}))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git" if name == "git" else None)

    result = check_git_checkout(tmp_path)

    assert result is not None
    ok, message = result
    assert ok is False
    assert str(missing) in message


def test_run_checks_includes_git_checkout_only_when_source_json_present(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(argv, **kw):
        class _R:
            stdout = "Docker Compose version v2.20.0"

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.doctor.run", fake_run)
    (tmp_path / ".env").write_text("AUTH_SECRET_KEY=abc\n")

    results_without = run_checks(tmp_path)
    assert not any(name == "git checkout" for name, _, _ in results_without)

    checkout = tmp_path / "repo"
    checkout.mkdir()
    (tmp_path / "source.json").write_text(json.dumps({"repo": str(checkout), "checkout": str(checkout)}))

    results_with = run_checks(tmp_path)
    assert any(name == "git checkout" for name, _, _ in results_with)


def test_run_checks_returns_list_of_results(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(argv, **kw):
        class _R:
            stdout = "Docker Compose version v2.20.0"

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.doctor.run", fake_run)
    (tmp_path / ".env").write_text("AUTH_SECRET_KEY=abc\n")

    results = run_checks(tmp_path)
    assert len(results) >= 4
    assert all(len(r) == 3 for r in results)  # (name, ok, message)
