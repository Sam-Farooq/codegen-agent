"""Repair returns only the files it changed. Everything else has to survive,
and getting this wrong silently deletes files between rounds."""
from codegen.graph import _merge
from codegen.state import FileEdit


def f(path, content="x"):
    return FileEdit(path=path, content=content)


def test_unchanged_files_survive_a_repair():
    out = _merge([f("a.py"), f("b.py")], [f("a.py", "fixed")])
    assert {e.path for e in out} == {"a.py", "b.py"}


def test_changed_file_content_is_replaced():
    out = _merge([f("a.py", "old")], [f("a.py", "new")])
    assert len(out) == 1 and out[0].content == "new"


def test_a_repair_may_add_a_file():
    out = _merge([f("a.py")], [f("conftest.py")])
    assert {e.path for e in out} == {"a.py", "conftest.py"}


def test_empty_repair_changes_nothing():
    assert {e.path for e in _merge([f("a.py"), f("b.py")], [])} == {"a.py", "b.py"}
