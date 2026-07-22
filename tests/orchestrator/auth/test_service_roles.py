import pytest

from orchestrator.auth.schemas import UserCreate, UserUpdate


def test_agent_role_passes_user_create_validation():
    user = UserCreate(username="bot", password="password1", role="agent")
    assert user.role == "agent"


def test_agent_role_passes_user_update_validation():
    update = UserUpdate(role="agent")
    assert update.role == "agent"


def test_unknown_role_rejected_by_user_create():
    with pytest.raises(ValueError):
        UserCreate(username="bot", password="password1", role="superuser")
