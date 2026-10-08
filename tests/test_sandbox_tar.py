import tarfile

from codegen.sandbox.runner import _tar
from codegen.state import FileEdit


def test_archive_contains_every_file_at_its_path():
    buf = _tar([FileEdit(path="pkg/mod.py", content="x = 1"),
                FileEdit(path="test_mod.py", content="def test(): pass")])
    with tarfile.open(fileobj=buf) as archive:
        assert sorted(archive.getnames()) == ["pkg/mod.py", "test_mod.py"]


def test_sizes_are_set_or_docker_silently_truncates():
    content = "a" * 5000
    buf = _tar([FileEdit(path="big.py", content=content)])
    with tarfile.open(fileobj=buf) as archive:
        assert archive.getmember("big.py").size == len(content.encode())


def test_unicode_survives_the_round_trip():
    buf = _tar([FileEdit(path="u.py", content="s = 'café'")])
    with tarfile.open(fileobj=buf) as archive:
        assert "café" in archive.extractfile("u.py").read().decode()
