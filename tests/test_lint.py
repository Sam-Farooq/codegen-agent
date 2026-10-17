"""The gate itself. These run the real ruff, which is why it is a dependency
and not a dev extra."""
import sys

from codegen.lint import Linter, _fit
from codegen.state import FileEdit


def f(path, content):
    return FileEdit(path=path, content=content)


async def test_a_syntax_error_is_reported():
    report = await Linter().check([f("m.py", "def total(items:\n    return 1\n")])
    assert not report.clean
    assert report.available
    assert "m.py:1" in report.findings
    assert "invalid-syntax" in report.findings


async def test_an_undefined_name_is_reported():
    report = await Linter().check([f("m.py", "def total(items):\n    return helper(items)\n")])
    assert not report.clean
    assert "F821" in report.findings
    assert "helper" in report.findings


async def test_a_file_in_a_subdirectory_is_checked_too():
    report = await Linter().check([f("pkg/m.py", "x = (1\n")])
    assert not report.clean
    assert "pkg/m.py" in report.findings


async def test_code_that_runs_is_clean():
    report = await Linter().check([
        f("m.py", "def total(items):\n    return sum(items)\n"),
        f("test_m.py", "from m import total\n\n\ndef test_total():\n    assert total([1]) == 1\n"),
    ])
    assert report.clean
    assert report.count == 0
    assert report.findings == ""


async def test_an_unused_import_is_not_worth_a_repair_round():
    """pytest passes on an unused import, so blocking on one would spend a
    model call to buy nothing. Only the rules that end a run are selected."""
    report = await Linter().check([f("m.py", "import os\nimport sys\n\n\ndef total():\n    return 1\n")])
    assert report.clean


async def test_a_suppression_comment_does_not_clear_the_gate():
    """A repair round can write `# noqa` instead of a fix. Python does not
    read the comment, so neither does the gate."""
    report = await Linter().check(
        [f("m.py", "def total(items):\n    return helper(items)  # noqa: F821\n")]
    )
    assert not report.clean
    assert "F821" in report.findings


async def test_an_absolute_path_is_refused_and_not_written(tmp_path):
    target = tmp_path / "written-by-the-model.py"
    report = await Linter().check([f(str(target), "x = 1\n")])
    assert not target.exists()
    assert not report.clean
    assert "escapes the work directory" in report.findings


async def test_a_traversing_path_is_refused_and_not_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = await Linter().check([f("../../escaped.py", "x = 1\n")])
    assert not report.clean
    assert "escapes the work directory" in report.findings
    assert not list(tmp_path.parent.parent.glob("escaped.py"))


async def test_a_refused_path_does_not_hide_a_real_finding(tmp_path):
    report = await Linter().check([
        f("/etc/codegen-should-never-write-this.py", "x = 1\n"),
        f("m.py", "def total(items:\n    return 1\n"),
    ])
    # One refusal plus whatever ruff makes of the file it could read.
    assert report.count >= 2
    assert "escapes the work directory" in report.findings
    assert "invalid-syntax" in report.findings


async def test_a_missing_linter_does_not_block_the_run():
    """The container is still the authority. A gate that cannot run has to
    get out of the way, not fail the round."""
    report = await Linter(command=["/nonexistent/ruff"]).check(
        [f("m.py", "def total(items:\n    return 1\n")]
    )
    assert report.clean
    assert not report.available
    assert report.count == 0


async def test_ruff_refusing_the_invocation_does_not_block_the_run():
    report = await Linter(command=[sys.executable, "-c", "raise SystemExit(2)"]).check(
        [f("m.py", "def total(items:\n    return 1\n")]
    )
    assert report.clean
    assert not report.available


async def test_a_refused_path_still_blocks_when_ruff_is_missing(tmp_path):
    """Nothing about a missing linter makes a host write acceptable."""
    report = await Linter(command=["/nonexistent/ruff"]).check(
        [f(str(tmp_path / "x.py"), "x = 1\n")]
    )
    assert not report.clean
    assert not report.available
    assert not (tmp_path / "x.py").exists()


def test_findings_are_cut_at_the_head_with_a_count_of_the_rest():
    lines = [f"m{i}.py:1:1: F821 Undefined name `x`" for i in range(500)]
    fitted = _fit(lines)
    assert len(fitted) <= 4000 + len("... 500 more findings")
    assert fitted.startswith("m0.py:1:1:")
    assert fitted.splitlines()[-1].endswith("more findings")
    # The count names what was dropped, not what was kept.
    dropped = int(fitted.splitlines()[-1].split()[1])
    assert dropped == 500 - (len(fitted.splitlines()) - 1)
