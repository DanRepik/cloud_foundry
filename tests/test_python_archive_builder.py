import os
import time
import zipfile

import pytest
from cloud_foundry.python_archive_builder import PythonArchiveBuilder
from unittest import mock


@pytest.fixture
def builder(tmp_path):
    # Minimal init, as we only test _parse_resource_url (no real dirs needed)
    return PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )


def test_stage_resource_file_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("hello")
    # Absolute file path
    builder._stage_resource(f"file://{src}", str(dst))
    assert dst.read_text().strip() == "hello"


def test_stage_resource_file_protocol_relative(tmp_path, monkeypatch):
    import os

    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        src = tmp_path / "rel_src.txt"
        dst = tmp_path / "rel_dst.txt"
        src.write_text("world")
        # Relative file path (no leading slash after file://)
        rel_src = "rel_src.txt"
        builder._stage_resource(f"file://{rel_src}", str(dst))
        assert dst.read_text().strip() == "world"
    finally:
        os.chdir(cwd)


def test_stage_resource_inline_content(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    dst = tmp_path / "inline.txt"
    builder._stage_resource("some inline content", str(dst))
    assert dst.read_text().strip() == "some inline content"


def test_stage_resource_pkg_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_package_resource") as m:
        builder._stage_resource("pkg://mypkg.module/resource/file.txt", "dst")
        m.assert_called_once_with("mypkg.module", "resource/file.txt", "dst")


def test_stage_resource_s3_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_s3_resource") as m:
        builder._stage_resource("s3://bucket/key/to/file.txt", "dst")
        m.assert_called_once_with("bucket", "key/to/file.txt", "dst")


def test_stage_resource_http_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_network_resource") as m:
        builder._stage_resource("http://example.com/file.txt", "dst")
        m.assert_called_once_with("http://example.com/file.txt", "dst")


def test_stage_resource_https_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test", sources={}, requirements=[], working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_network_resource") as m:
        builder._stage_resource("https://example.com/file.txt", "dst")
        m.assert_called_once_with("https://example.com/file.txt", "dst")


def test_manylinux_platforms_for_x86_64():
    assert PythonArchiveBuilder.manylinux_platforms_for_architecture("x86_64") == [
        "manylinux2014_x86_64",
        "manylinux_2_17_x86_64",
    ]


def test_manylinux_platforms_for_arm64():
    assert PythonArchiveBuilder.manylinux_platforms_for_architecture("arm64") == [
        "manylinux2014_aarch64",
        "manylinux_2_17_aarch64",
    ]


def test_cache_hash_includes_target_architecture_and_requirements(tmp_path):
    common_kwargs = {
        "name": "test",
        "sources": {"handler.py": "def handler(event, context):\n    return event"},
        "working_dir": str(tmp_path),
    }
    with (
        mock.patch.object(PythonArchiveBuilder, "install_requirements"),
        mock.patch.object(PythonArchiveBuilder, "build_archive"),
    ):
        builder_x86 = PythonArchiveBuilder(
            requirements=["psycopg2-binary==2.9.9"],
            target_architecture="x86_64",
            **common_kwargs,
        )
        builder_arm = PythonArchiveBuilder(
            requirements=["psycopg2-binary==2.9.9"],
            target_architecture="arm64",
            **common_kwargs,
        )
        builder_req = PythonArchiveBuilder(
            requirements=["psycopg2-binary==2.9.10"],
            target_architecture="x86_64",
            **common_kwargs,
        )

    assert builder_x86.hash() != builder_arm.hash()
    assert builder_x86.hash() != builder_req.hash()


def test_requirements_none_does_not_raise(tmp_path):
    # A Lambda with no extra dependencies (e.g. boto3-only) omits
    # `requirements` entirely, leaving it None -- _build_cache_hash must not
    # blow up iterating over that.
    with (
        mock.patch.object(PythonArchiveBuilder, "install_requirements"),
        mock.patch.object(PythonArchiveBuilder, "build_archive"),
    ):
        builder = PythonArchiveBuilder(
            name="test",
            sources={"handler.py": "def handler(event, context):\n    return event"},
            requirements=None,
            working_dir=str(tmp_path),
        )

    assert builder.hash()


def _fake_install(pyc_body: bytes):
    """Stand-in for pip: installs one module plus the kind of bytecode pip
    compiles by default, whose bytes differ from one install to the next."""

    def install(self):
        pkg = os.path.join(self._libs, "fakepkg")
        os.makedirs(os.path.join(pkg, "__pycache__"), exist_ok=True)
        with open(os.path.join(pkg, "__init__.py"), "w") as f:
            f.write("VALUE = 1\n")
        with open(os.path.join(pkg, "__pycache__", "__init__.cpython-311.pyc"), "wb") as f:
            f.write(pyc_body)

    return install


def _build(working_dir, pyc_body: bytes) -> PythonArchiveBuilder:
    with mock.patch.object(
        PythonArchiveBuilder, "install_requirements", _fake_install(pyc_body)
    ):
        return PythonArchiveBuilder(
            name="test",
            sources={"handler.py": "def handler(event, context):\n    return event"},
            requirements=["fakepkg==1.0"],
            working_dir=str(working_dir),
        )


def _zip_bytes(builder: PythonArchiveBuilder) -> bytes:
    with open(builder.location(), "rb") as f:
        return f.read()


def test_fresh_builds_of_the_same_tree_are_byte_identical(tmp_path):
    # Two builds in separate working dirs (a CI runner starts with an empty
    # temp/), seconds apart, with bytecode that differs between installs.
    first = _build(tmp_path / "a", b"pyc-first-install")
    time.sleep(1.1)  # zip timestamps have 2-second resolution; cross a tick
    second = _build(tmp_path / "b", b"pyc-second-install")

    assert first.hash() == second.hash()
    assert _zip_bytes(first) == _zip_bytes(second)


def test_archive_leaves_out_bytecode_and_keeps_sources(tmp_path):
    builder = _build(tmp_path, b"pyc")

    with zipfile.ZipFile(builder.location()) as archive:
        names = archive.namelist()
        infos = archive.infolist()

    assert "handler.py" in names
    assert "fakepkg/__init__.py" in names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}


def test_source_change_still_changes_the_hash(tmp_path):
    base = _build(tmp_path / "a", b"pyc")
    with mock.patch.object(PythonArchiveBuilder, "install_requirements", _fake_install(b"pyc")):
        changed = PythonArchiveBuilder(
            name="test",
            sources={"handler.py": "def handler(event, context):\n    return None"},
            requirements=["fakepkg==1.0"],
            working_dir=str(tmp_path / "b"),
        )

    assert base.hash() != changed.hash()
    assert _zip_bytes(base) != _zip_bytes(changed)


def test_pip_is_told_not_to_compile_bytecode(tmp_path):
    with mock.patch("cloud_foundry.python_archive_builder.subprocess.check_call") as check_call:
        PythonArchiveBuilder(
            name="test",
            sources={"handler.py": "def handler(event, context):\n    return event"},
            requirements=["fakepkg==1.0"],
            working_dir=str(tmp_path),
        )

    command = check_call.call_args_list[0].args[0]
    assert "--no-compile" in command
