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
