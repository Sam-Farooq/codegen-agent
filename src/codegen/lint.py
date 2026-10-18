"""Static analysis before the container.

The expensive part of a round is the sandbox: an image check, a fresh
container, a pytest start. A file that will not parse, or that calls a name
nothing defines, does not need any of that to be known wrong. So every file
set goes past ruff on the host first, and a finding that was certainly going
to end the suite before a single test ran becomes a repair round with no
container at all.

Three decisions here are deliberate.

Only rules that stop execution are selected. Blocking on an unused import
would spend a model call to fix something pytest would have passed, which is
a worse trade than the container start it saves.

noqa comments are ignored. The gate is predicting what Python will do, and a
suppression comment does not change that; without this flag a repair round
can silence the gate instead of fixing the code.

A linter that cannot be run does not block the loop. The container is still
the authority on whether the code works. ruff only gets to say first what it
would certainly have said.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from codegen.state import FileEdit, LintReport

log = logging.getLogger(__name__)

# invalid-syntax is reported whatever is selected. The rest are the rules that
# name something Python will not resolve when it gets there: an undefined
# name, an undefined name in __all__, a local read before it is assigned. E9
# also carries E902, which is how an unreadable file arrives.
RULES = "E9,F821,F822,F823"

# Matches the sandbox image and this project's requires-python floor. A
# sandbox_image on a newer Python is parsed conservatively: syntax added after
# 3.11 reads as a syntax error here, which costs a repair round rather than a
# wrong result.
TARGET_VERSION = "py311"

TIMEOUT_SECONDS = 30
MAX_FINDINGS_CHARS = 4000

_FINDING = re.compile(r"^.+?:\d+:\d+: \S")


def _ruff_command() -> list[str]:
    binary = shutil.which("ruff")
    if binary:
        return [binary]
    # Installed as a wheel whose script directory is not on PATH.
    return [sys.executable, "-m", "ruff"]


def _destination(root: Path, path: str) -> Path | None:
    """Where a generated file goes, or None if it would land outside root.

    These files are written to the host for ruff to read, so an absolute path
    or a `..` in a generated filename is a host write. The sandbox tar has the
    same shape of problem and a container to absorb it; here there is nothing
    between the string and the filesystem but this function.
    """
    try:
        resolved = (root / path).resolve()
        base = root.resolve()
    except OSError:
        return None
    if resolved == base or not resolved.is_relative_to(base):
        return None
    return resolved


def _write(files: list[FileEdit], root: Path) -> list[str]:
    """Writes what it can and returns the paths it refused."""
    refused = []
    for f in files:
        destination = _destination(root, f.path)
        if destination is None:
            refused.append(f.path)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f.content, encoding="utf-8")
    return refused


def _fit(lines: list[str], budget: int = MAX_FINDINGS_CHARS) -> str:
    """Head, not tail. ruff emits a list and the first entries are as real as
    the last; pytest is truncated the other way because its summary is last.
    """
    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            kept.append(f"... {len(lines) - len(kept)} more findings")
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


class Linter:
    def __init__(self, command: list[str] | None = None):
        self.command = command or _ruff_command()

    async def check(self, files: list[FileEdit]) -> LintReport:
        return await asyncio.to_thread(self._check, files)

    def _check(self, files: list[FileEdit]) -> LintReport:
        with tempfile.TemporaryDirectory(prefix="codegen-lint-") as tmp:
            root = Path(tmp)
            refused = [f"{p}:1:1: path escapes the work directory, write a relative path"
                       for p in _write(files, root)]
            available, findings = self._ruff(root)

        if not available:
            return LintReport(clean=not refused, findings=_fit(refused),
                              count=len(refused), available=False)

        lines = refused + findings
        return LintReport(clean=not lines, findings=_fit(lines), count=len(lines))

    def _ruff(self, root: Path) -> tuple[bool, list[str]]:
        argv = [*self.command, "check", "--isolated", "--no-cache", "--ignore-noqa",
                "--output-format=concise", f"--target-version={TARGET_VERSION}",
                f"--select={RULES}", "."]
        try:
            done = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                                  timeout=TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("ruff did not run (%s); the container decides", exc)
            return False, []

        # 0 is clean and 1 is findings. Anything else is ruff refusing the
        # invocation, which says nothing about the generated code.
        if done.returncode not in (0, 1):
            log.warning("ruff exited %s: %s", done.returncode, done.stderr.strip()[:200])
            return False, []

        return True, [ln for ln in done.stdout.splitlines() if _FINDING.match(ln)]
