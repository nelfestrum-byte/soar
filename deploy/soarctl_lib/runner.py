"""Single choke point for shelling out — every other soarctl_lib module builds
argv lists and calls run(), nothing else touches subprocess directly.
"""

import subprocess


class CommandError(RuntimeError):
    def __init__(self, argv: list[str], returncode: int, stderr):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        message = stderr if isinstance(stderr, str) else "(binary output)"
        super().__init__(f"command failed ({returncode}): {' '.join(argv)}\n{message}")


def run(
    argv: list[str],
    cwd=None,
    check: bool = True,
    env: dict[str, str] | None = None,
    stream: bool = False,
    input_text: str | bytes | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """stream=True inherits the caller's stdio instead of capturing it — for
    long-running/interactive commands (`compose logs -f`, `compose up`
    attached) where buffering output until exit isn't useful. input_text
    feeds the child's stdin (e.g. piping a SQL dump into `psql`). text=False
    captures stdout/stderr as bytes instead of str — needed for the backup
    volume tar, which is binary gzip data (not a --deploy convention, just
    what tar produces).
    """
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=not stream,
        text=text,
        input=input_text,
    )
    if check and result.returncode != 0:
        stderr = result.stderr or "(see output above)"
        raise CommandError(argv, result.returncode, stderr)
    return result
