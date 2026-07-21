import asyncio
import os
from dataclasses import dataclass

from loguru import logger


@dataclass
class GitCommit:
    hash: str
    message: str
    author: str
    timestamp: str


class GitManager:
    def __init__(self, repo_path: str, author_name: str, author_email: str):
        self.repo_path = repo_path
        self.author_name = author_name
        self.author_email = author_email

    async def _run(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": self.author_name,
            "GIT_AUTHOR_EMAIL": self.author_email,
            "GIT_COMMITTER_NAME": self.author_name,
            "GIT_COMMITTER_EMAIL": self.author_email,
        }
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=self.repo_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {stderr.decode()}")
        return stdout.decode()

    async def ensure_repo(self) -> None:
        git_dir = os.path.join(self.repo_path, ".git")
        if not os.path.exists(git_dir):
            await self._run("init")
            await self._run("add", ".")
            await self._run(
                "commit", "-m", "Initial commit",
                f"--author={self.author_name} <{self.author_email}>",
            )
            logger.info("Initialized git repository")

    async def commit(
        self, filepath: str, message: str,
        author_name: str | None = None, author_email: str | None = None,
    ) -> str:
        name = author_name or self.author_name
        email = author_email or self.author_email

        await self._run("add", "--", filepath)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            f"--author={name} <{email}>",
            cwd=self.repo_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            combined = (stdout.decode() + stderr.decode()).lower()
            if "nothing to commit" in combined or "no changes" in combined:
                return ""
            raise RuntimeError(f"git commit failed: {stderr.decode()}")
        result = await self._run("rev-parse", "--short", "HEAD")
        return result.strip()

    async def history(self, filepath: str, limit: int = 20) -> list[GitCommit]:
        output = await self._run(
            "log", "--follow", "-n", str(limit),
            "--format=%H%x00%s%x00%an%x00%ai", "--", filepath,
        )
        commits = []
        for line in output.strip().splitlines():
            if not line:
                continue
            parts = line.split("\x00", 3)
            if len(parts) == 4:
                commits.append(GitCommit(
                    hash=parts[0],
                    message=parts[1],
                    author=parts[2],
                    timestamp=parts[3],
                ))
        return commits

    async def get_content(self, filepath: str, commit: str) -> str:
        return await self._run("show", f"{commit}:{filepath}")

    async def diff(self, filepath: str, commit_a: str, commit_b: str) -> str:
        return await self._run("diff", commit_a, commit_b, "--", filepath)

    async def restore(self, filepath: str, commit: str) -> None:
        await self._run("checkout", commit, "--", filepath)
        await self.commit(filepath, f"Restore to {commit}")
