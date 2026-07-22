import os

import pytest
from fastapi import HTTPException

from orchestrator.core.git_manager import GitManager
from orchestrator.core.history import diff_versions, get_version, list_history, restore_version


@pytest.fixture
def git_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "test.txt").write_text("v1")
    return str(repo_dir)


@pytest.fixture
async def git(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    await gm.ensure_repo()
    return gm


@pytest.mark.asyncio
async def test_list_history(git, git_repo):
    with open(os.path.join(git_repo, "test.txt"), "w") as f:
        f.write("v2")
    await git.commit("test.txt", "Update to v2")

    entries = await list_history(git, "test.txt")
    assert len(entries) == 2
    assert entries[0]["message"] == "Update to v2"
    assert {"hash", "message", "author", "timestamp"} <= entries[0].keys()


@pytest.mark.asyncio
async def test_get_version(git, git_repo):
    history = await git.history("test.txt")
    first_commit = history[-1].hash
    content = await get_version(git, "test.txt", first_commit)
    assert content == "v1"


@pytest.mark.asyncio
async def test_get_version_not_found(git):
    with pytest.raises(HTTPException) as exc_info:
        await get_version(git, "test.txt", "deadbeef")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_diff_versions(git, git_repo):
    with open(os.path.join(git_repo, "test.txt"), "w") as f:
        f.write("v2")
    await git.commit("test.txt", "Update to v2")

    history = await git.history("test.txt")
    diff = await diff_versions(git, "test.txt", history[1].hash, history[0].hash)
    assert "v1" in diff
    assert "v2" in diff


@pytest.mark.asyncio
async def test_diff_versions_not_found(git):
    with pytest.raises(HTTPException) as exc_info:
        await diff_versions(git, "test.txt", "deadbeef", "beefdead")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_version(git, git_repo):
    with open(os.path.join(git_repo, "test.txt"), "w") as f:
        f.write("v2")
    await git.commit("test.txt", "Update to v2")

    history = await git.history("test.txt")
    first_commit = history[-1].hash
    await restore_version(git, "test.txt", first_commit, "alice", "alice@soar.local")

    with open(os.path.join(git_repo, "test.txt")) as f:
        assert f.read() == "v1"

    history = await git.history("test.txt")
    assert history[0].author == "alice"


@pytest.mark.asyncio
async def test_restore_version_not_found(git):
    with pytest.raises(HTTPException) as exc_info:
        await restore_version(git, "test.txt", "deadbeef", "alice", "alice@soar.local")
    assert exc_info.value.status_code == 404
