from unittest import mock

from cloud_foundry.pulumi.ui_publisher import UIPublisher


def test_cache_control_for_payload_and_hashed_assets():
    assert (
        UIPublisher.cache_control_for_key("contract/_payload.json")
        == "public, max-age=31536000, immutable"
    )
    assert (
        UIPublisher.cache_control_for_key("_nuxt/app.abc123.js")
        == "public, max-age=31536000, immutable"
    )


def test_cache_control_for_html_and_generic_json():
    assert (
        UIPublisher.cache_control_for_key("contract/index.html")
        == "public, max-age=300, s-maxage=86400, stale-while-revalidate=3600"
    )
    assert (
        UIPublisher.cache_control_for_key("manifest.webmanifest")
        == "public, max-age=3600, stale-while-revalidate=300"
    )


import boto3
import pytest
from moto import mock_aws

from cloud_foundry.pulumi.ui_publisher import SiteFilesProvider

BUCKET = "site"
CONNECTION = {"region": "us-east-1"}


def _entry(path, sha, content_type="text/html", cache="public, max-age=300"):
    return {"path": path, "sha256": sha, "content_type": content_type, "cache_control": cache}


def _props(source_dir, files, bucket=BUCKET):
    return {"bucket": bucket, "prefix": "", "source_dir": str(source_dir), "files": files, "connection": CONNECTION}


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _keys(s3):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def test_diff_ignores_the_local_checkout_path():
    old = _props("/home/a/site", {"index.html": _entry("index.html", "1")})
    new = _props("/runner/work/site", {"index.html": _entry("index.html", "1")})

    assert not SiteFilesProvider().diff("id", old, new).changes


def test_diff_flags_content_header_and_membership_changes():
    provider = SiteFilesProvider()
    base = _props("/s", {"a.js": _entry("a.js", "1")})

    assert provider.diff("id", base, _props("/s", {"a.js": _entry("a.js", "2")})).changes
    assert provider.diff("id", base, _props("/s", {"a.js": _entry("a.js", "1", cache="no-cache")})).changes
    assert provider.diff("id", base, _props("/s", {})).changes
    moved = provider.diff("id", base, _props("/s", {"a.js": _entry("a.js", "1")}, bucket="other"))
    assert moved.replaces == ["bucket"] and moved.delete_before_replace is False


def test_create_update_and_delete_keep_the_bucket_in_step(s3, tmp_path):
    (tmp_path / "index.html").write_text("v1")
    (tmp_path / "old.js").write_text("old")
    provider = SiteFilesProvider()
    v1 = _props(tmp_path, {
        "index.html": _entry("index.html", "1"),
        "old.js": _entry("old.js", "o", "text/javascript", "public, max-age=31536000, immutable"),
    })
    provider.create(v1)
    assert _keys(s3) == ["index.html", "old.js"]
    head = s3.head_object(Bucket=BUCKET, Key="old.js")
    assert head["ContentType"] == "text/javascript"
    assert head["CacheControl"] == "public, max-age=31536000, immutable"

    (tmp_path / "index.html").write_text("v2")
    (tmp_path / "new.js").write_text("new")
    v2 = _props(tmp_path, {
        "index.html": _entry("index.html", "2"),
        "new.js": _entry("new.js", "n", "text/javascript"),
    })
    with mock.patch("cloud_foundry.pulumi.ui_publisher._upload", wraps=__import__(
        "cloud_foundry.pulumi.ui_publisher", fromlist=["_upload"])._upload) as upload:
        provider.update("id", v1, v2)
    assert upload.call_args.args[2] == ["index.html", "new.js"]  # only what changed
    assert _keys(s3) == ["index.html", "new.js"]
    assert s3.get_object(Bucket=BUCKET, Key="index.html")["Body"].read() == b"v2"

    provider.delete("id", v2)
    assert _keys(s3) == []
    s3.delete_bucket(Bucket=BUCKET)  # empty, so a non-force_destroy bucket can go


def test_build_manifest_hashes_files_relative_to_the_build(tmp_path):
    (tmp_path / "_nuxt").mkdir()
    (tmp_path / "_nuxt" / "app.js").write_text("x")
    publisher = UIPublisher.__new__(UIPublisher)

    manifest = publisher.build_manifest(str(tmp_path), "")

    assert manifest == {
        "_nuxt/app.js": {
            "path": "_nuxt/app.js",
            "sha256": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
            "content_type": "text/javascript",
            "cache_control": "public, max-age=31536000, immutable",
        }
    }
