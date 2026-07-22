from fastapi import HTTPException


async def list_history(git, filepath: str, limit: int = 20) -> list[dict]:
    commits = await git.history(filepath, limit=limit)
    return [
        {"hash": c.hash, "message": c.message, "author": c.author, "timestamp": c.timestamp}
        for c in commits
    ]


async def get_version(git, filepath: str, commit: str) -> str:
    try:
        return await git.get_content(filepath, commit)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Version not found: {e}") from e


async def diff_versions(git, filepath: str, commit_a: str, commit_b: str) -> str:
    try:
        return await git.diff(filepath, commit_a, commit_b)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Diff failed: {e}") from e


async def restore_version(
    git, filepath: str, commit: str, author_name: str, author_email: str,
) -> None:
    try:
        await git.restore(filepath, commit, author_name=author_name, author_email=author_email)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=f"Restore failed: {e}") from e
