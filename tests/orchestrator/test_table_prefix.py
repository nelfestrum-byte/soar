"""Table prefix is baked in at model-import time (see db/base.py), so it can only be
observed in a fresh interpreter — run assertions in a subprocess before anything else
in the test session has imported orchestrator.auth.models / orchestrator.store.models.
"""

import subprocess
import sys
import textwrap

_AUTH_SCRIPT = textwrap.dedent("""
    from orchestrator.db.base import configure_table_prefix
    configure_table_prefix("test_")

    from orchestrator.auth.models import ApiKey, RefreshToken, User
    from orchestrator.store.models import JobRecord

    assert User.__tablename__ == "test_users", User.__tablename__
    assert RefreshToken.__tablename__ == "test_refresh_tokens", RefreshToken.__tablename__
    assert ApiKey.__tablename__ == "test_api_keys", ApiKey.__tablename__
    assert JobRecord.__tablename__ == "test_workflow_jobs", JobRecord.__tablename__

    fks = list(RefreshToken.__table__.c.user_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "test_users.id", fks[0].target_fullname
""")

_EMPTY_PREFIX_SCRIPT = textwrap.dedent("""
    from orchestrator.auth.models import ApiKey, RefreshToken, User
    from orchestrator.store.models import JobRecord

    assert User.__tablename__ == "users", User.__tablename__
    assert RefreshToken.__tablename__ == "refresh_tokens", RefreshToken.__tablename__
    assert ApiKey.__tablename__ == "api_keys", ApiKey.__tablename__
    assert JobRecord.__tablename__ == "workflow_jobs", JobRecord.__tablename__
""")


def test_table_prefix_applied_to_auth_models_and_fk():
    result = subprocess.run(
        [sys.executable, "-c", _AUTH_SCRIPT],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_prefix_is_empty_string_noop():
    result = subprocess.run(
        [sys.executable, "-c", _EMPTY_PREFIX_SCRIPT],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
