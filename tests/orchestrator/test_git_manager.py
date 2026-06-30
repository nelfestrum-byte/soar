import os

import pytest

from orchestrator.core.git_manager import GitManager


@pytest.fixture
def git_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "test.txt").write_text("initial")
    return str(repo_dir)


@pytest.mark.asyncio
async def test_git_manager_init(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    assert gm.repo_path == git_repo


@pytest.mark.asyncio
async def test_git_manager_ensure_repo(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    await gm.ensure_repo()
    assert os.path.exists(os.path.join(git_repo, ".git"))


@pytest.mark.asyncio
async def test_git_manager_commit(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    await gm.ensure_repo()

    (repo_dir := os.path.join(git_repo, "new_file.txt"))
    with open(repo_dir, "w") as f:
        f.write("new content")

    commit_hash = await gm.commit("new_file.txt", "Add new file")
    assert len(commit_hash) > 0


@pytest.mark.asyncio
async def test_git_manager_commit_nothing(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    await gm.ensure_repo()

    commit_hash = await gm.commit("test.txt", "No changes")
    assert commit_hash == ""


@pytest.mark.asyncio
async def test_git_manager_history(git_repo):
    gm = GitManager(repo_path=git_repo, author_name="Test", author_email="test@test.com")
    await gm.ensure_repo()

    history = await gm.history("test.txt")
    assert len(history) > 0
    assert history[0].message == "Initial commit"
