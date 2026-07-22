import pytest

from deploy.soarctl_lib.env import generate_secrets, init_instance, render_template, update_version


def test_generate_secrets_lengths():
    secrets = generate_secrets()
    assert len(secrets["AUTH_SECRET_KEY"]) == 64  # 32 bytes hex
    assert len(secrets["POSTGRES_PASSWORD"]) == 32  # 16 bytes hex
    assert len(secrets["SOAR_WEBHOOK_TOKEN"]) == 32  # 16 bytes hex
    assert all(c in "0123456789abcdef" for c in secrets["AUTH_SECRET_KEY"])


def test_generate_secrets_are_not_reused_across_calls():
    a = generate_secrets()
    b = generate_secrets()
    assert a["AUTH_SECRET_KEY"] != b["AUTH_SECRET_KEY"]
    assert a["POSTGRES_PASSWORD"] != b["POSTGRES_PASSWORD"]


def test_render_template_substitutes_known_vars():
    text = 'url: postgresql://soar:${POSTGRES_PASSWORD}@postgres:5432/soar\nkey: "${AUTH_SECRET_KEY}"\n'
    out = render_template(text, {"POSTGRES_PASSWORD": "pw123", "AUTH_SECRET_KEY": "sk456"})
    assert "pw123" in out
    assert "sk456" in out
    assert "${" not in out


def test_render_template_leaves_unknown_dollar_signs_alone():
    text = "literal: $UNRELATED and ${also_unrelated}"
    out = render_template(text, {"AUTH_SECRET_KEY": "sk"})
    assert out == text


def test_init_instance_writes_env_and_config(tmp_path):
    (tmp_path / "config.yaml.template").write_text(
        'auth:\n  secret_key: "${AUTH_SECRET_KEY}"\n'
        "database:\n  url: postgresql+asyncpg://soar:${POSTGRES_PASSWORD}@postgres:5432/soar\n"
    )
    (tmp_path / "VERSION").write_text("1.2.3\n")

    init_instance(tmp_path)

    env_text = (tmp_path / ".env").read_text()
    assert "SOAR_VERSION=1.2.3" in env_text
    assert "AUTH_SECRET_KEY=" in env_text
    assert "POSTGRES_PASSWORD=" in env_text
    assert "SOAR_WEBHOOK_TOKEN=" in env_text

    config_text = (tmp_path / "config.yaml").read_text()
    assert "${" not in config_text
    assert "secret_key:" in config_text


def test_init_instance_refuses_to_overwrite_existing_env(tmp_path):
    (tmp_path / "config.yaml.template").write_text("auth:\n  secret_key: \"${AUTH_SECRET_KEY}\"\n")
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / ".env").write_text("EXISTING=1\n")

    with pytest.raises(FileExistsError):
        init_instance(tmp_path)

    assert (tmp_path / ".env").read_text() == "EXISTING=1\n"


def test_init_instance_force_overwrites(tmp_path):
    (tmp_path / "config.yaml.template").write_text("auth:\n  secret_key: \"${AUTH_SECRET_KEY}\"\n")
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / ".env").write_text("EXISTING=1\n")

    init_instance(tmp_path, force=True)

    assert "EXISTING=1" not in (tmp_path / ".env").read_text()


def test_init_instance_missing_template_raises(tmp_path):
    (tmp_path / "VERSION").write_text("1.2.3\n")
    with pytest.raises(FileNotFoundError):
        init_instance(tmp_path)


def test_update_version_replaces_existing_line_only(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("AUTH_SECRET_KEY=keep-me\nSOAR_VERSION=1.0.0\nPOSTGRES_PASSWORD=keep-too\n")

    update_version(tmp_path, "2.0.0")

    lines = env_path.read_text().splitlines()
    assert "SOAR_VERSION=2.0.0" in lines
    assert "AUTH_SECRET_KEY=keep-me" in lines
    assert "POSTGRES_PASSWORD=keep-too" in lines
    assert "SOAR_VERSION=1.0.0" not in lines


def test_update_version_missing_env_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        update_version(tmp_path, "2.0.0")
