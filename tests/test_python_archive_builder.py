import pytest
from cloud_foundry.python_archive_builder import PythonArchiveBuilder
from unittest import mock


@pytest.fixture
def builder(tmp_path):
    # Minimal init, as we only test _parse_resource_url (no real dirs needed)
    return PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
    )

def test_stage_resource_file_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
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
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
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
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
    )
    dst = tmp_path / "inline.txt"
    builder._stage_resource("some inline content", str(dst))
    assert dst.read_text().strip() == "some inline content"

def test_stage_resource_pkg_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_package_resource") as m:
        builder._stage_resource("pkg://mypkg.module/resource/file.txt", "dst")
        m.assert_called_once_with("mypkg.module", "resource/file.txt", "dst")

def test_stage_resource_s3_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_s3_resource") as m:
        builder._stage_resource("s3://bucket/key/to/file.txt", "dst")
        m.assert_called_once_with("bucket", "key/to/file.txt", "dst")

def test_stage_resource_http_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
    )
    with mock.patch.object(builder, "_get_network_resource") as m:
        builder._stage_resource("http://example.com/file.txt", "dst")
        m.assert_called_once_with("http://example.com/file.txt", "dst")

def test_stage_resource_https_protocol(tmp_path):
    builder = PythonArchiveBuilder(
        name="test",
        sources={},
        requirements=[],
        working_dir=str(tmp_path)
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
    with mock.patch.object(PythonArchiveBuilder, "install_requirements"), mock.patch.object(
        PythonArchiveBuilder, "build_archive"
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
