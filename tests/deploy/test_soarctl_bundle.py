import tarfile
from pathlib import Path

from deploy.soarctl_lib.bundle import BASE_IMAGES, build_images, install, package


def _make_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    prod = repo / "deploy" / "prod"
    prod.mkdir(parents=True)
    (prod / "docker-compose.yml").write_text("services: {}\n")
    (prod / "config.yaml.template").write_text("auth:\n  secret_key: \"${AUTH_SECRET_KEY}\"\n")
    (prod / "Dockerfile.orchestrator").write_text("FROM python:3.11-slim\n")
    (prod / "Dockerfile.ui").write_text("FROM nginx:alpine\n")

    lib = repo / "deploy" / "soarctl_lib"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("")
    (lib / "runner.py").write_text("# stub\n")
    pycache = lib / "__pycache__"
    pycache.mkdir()
    (pycache / "runner.cpython-311.pyc").write_bytes(b"stale bytecode")
    (repo / "deploy" / "soarctl").write_text("#!/usr/bin/env python3\n")
    return repo


def test_package_builds_and_pulls_and_saves(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    output = tmp_path / "out" / "soar-bundle-1.2.3.tar.gz"
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "save"]:
            # simulate `docker save -o <path>` actually writing the file
            out_path = Path(argv[argv.index("-o") + 1])
            out_path.write_bytes(b"fake-images-tar")

        class _R:
            stdout = ""

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)

    result = package(repo, version="1.2.3", output=output)

    assert result == output
    assert output.exists()

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    pull_calls = [c for c in calls if c[:2] == ["docker", "pull"]]
    save_calls = [c for c in calls if c[:2] == ["docker", "save"]]
    assert len(build_calls) == 2
    assert any("soar-orchestrator:1.2.3" in c for c in build_calls)
    assert any("soar-ui:1.2.3" in c for c in build_calls)
    assert {c[2] for c in pull_calls} == set(BASE_IMAGES)
    assert len(save_calls) == 1

    with tarfile.open(output) as tar:
        names = set(tar.getnames())
    assert "docker-compose.yml" in names
    assert "config.yaml.template" in names
    assert "VERSION" in names
    assert "soarctl" in names
    assert "soarctl_lib/runner.py" in names
    assert "images.tar" in names
    assert not any("__pycache__" in n for n in names)


def test_build_images_builds_and_pulls(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)

    orchestrator_tag, ui_tag = build_images(repo, "1.2.3")

    assert orchestrator_tag == "soar-orchestrator:1.2.3"
    assert ui_tag == "soar-ui:1.2.3"

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    pull_calls = [c for c in calls if c[:2] == ["docker", "pull"]]
    assert len(build_calls) == 2
    assert any("soar-orchestrator:1.2.3" in c for c in build_calls)
    assert any("soar-ui:1.2.3" in c for c in build_calls)
    assert {c[2] for c in pull_calls} == set(BASE_IMAGES)


def test_build_images_passes_pip_index_url_when_env_set(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)
    monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.yandex.ru/pypi/simple")

    build_images(repo, "1.2.3")

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    orchestrator_build = next(c for c in build_calls if "soar-orchestrator:1.2.3" in c)
    assert "--build-arg" in orchestrator_build
    idx = orchestrator_build.index("--build-arg")
    assert orchestrator_build[idx + 1] == "PIP_INDEX_URL=https://mirror.yandex.ru/pypi/simple"

    ui_build = next(c for c in build_calls if "soar-ui:1.2.3" in c)
    assert "--build-arg" not in ui_build


def test_build_images_omits_pip_index_url_build_arg_when_env_unset(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)

    build_images(repo, "1.2.3")

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    assert not any("--build-arg" in c for c in build_calls)


def test_build_images_falls_back_to_empty_basepack_when_sibling_missing(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)

    build_images(repo, "1.2.3")

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    orchestrator_build = next(c for c in build_calls if "soar-orchestrator:1.2.3" in c)
    basepack_arg = next(a for a in orchestrator_build if a.startswith("basepack="))
    basepack_dir = Path(basepack_arg.split("=", 1)[1])
    assert basepack_dir != repo.parent / "soar-content-pack"
    assert basepack_dir.is_dir()
    assert list(basepack_dir.iterdir()) == []


def test_build_images_uses_sibling_content_pack_when_present(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    content_pack = repo.parent / "soar-content-pack"
    content_pack.mkdir()
    (content_pack / "manifest.yaml").write_text("name: test\n")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)

    build_images(repo, "1.2.3")

    build_calls = [c for c in calls if c[:2] == ["docker", "build"]]
    orchestrator_build = next(c for c in build_calls if "soar-orchestrator:1.2.3" in c)
    assert f"basepack={content_pack}" in orchestrator_build


def test_install_extracts_and_loads_and_cleans_up(tmp_path, monkeypatch):
    bundle = tmp_path / "soar-bundle-1.2.3.tar.gz"
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "docker-compose.yml").write_text("services: {}\n")
    (staging / "VERSION").write_text("1.2.3\n")
    (staging / "images.tar").write_bytes(b"fake-images-tar")
    with tarfile.open(bundle, "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(item, arcname=item.name)

    dest = tmp_path / "instance"
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)

        class _R:
            stdout = ""

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", fake_run)

    result = install(bundle, dest)

    assert result == dest
    assert (dest / "docker-compose.yml").exists()
    assert (dest / "VERSION").read_text().strip() == "1.2.3"
    assert not (dest / "images.tar").exists()

    load_calls = [c for c in calls if c[:2] == ["docker", "load"]]
    assert len(load_calls) == 1
    assert "-i" in load_calls[0]


def test_install_on_existing_instance_bumps_version_without_touching_secrets(tmp_path, monkeypatch):
    bundle = tmp_path / "soar-bundle-2.0.0.tar.gz"
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "docker-compose.yml").write_text("services: {}\n")
    (staging / "VERSION").write_text("2.0.0\n")
    (staging / "images.tar").write_bytes(b"fake-images-tar")
    with tarfile.open(bundle, "w:gz") as tar:
        for item in staging.iterdir():
            tar.add(item, arcname=item.name)

    dest = tmp_path / "instance"
    dest.mkdir()
    (dest / ".env").write_text("AUTH_SECRET_KEY=keep-me\nSOAR_VERSION=1.0.0\n")

    monkeypatch.setattr("deploy.soarctl_lib.bundle.run", lambda argv, **kw: type("R", (), {"stdout": ""})())

    install(bundle, dest)

    env_text = (dest / ".env").read_text()
    assert "SOAR_VERSION=2.0.0" in env_text
    assert "AUTH_SECRET_KEY=keep-me" in env_text
