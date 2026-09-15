"""
Regression tests: Function's Lambda code upload path.

- No code_bucket + archive under the ~50MB direct-upload limit: uses
  code=FileArchive(...) as before.
- No code_bucket + archive over the limit: raises a clear ValueError
  pointing at code_bucket=, instead of letting AWS's own
  RequestEntityTooLargeException surface after a slow apply attempt
  (Pulumi resource creation is async, so a plain try/except around the
  resource declaration can't catch that error -- the size is checked
  proactively instead).
- code_bucket given (plain bucket name) + archive over the limit:
  succeeds, uploads via S3 (s3Bucket=/s3Key=) instead of inline.

Uses pulumi's mock runtime (no AWS/network access needed).
"""

import pytest
import pulumi

from cloud_foundry.pulumi.function import DIRECT_UPLOAD_SIZE_LIMIT, Function


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("bucket", args.inputs.get("bucket", args.name))
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "aws:iam/getPolicyDocument:getPolicyDocument":
            return {"json": "{}"}
        return {}


def _drain_pulumi_event_loop():
    import asyncio

    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.2))


def _make_archive(tmp_path, size_bytes: int) -> str:
    # Sparse file -- same reported size as a real archive without
    # actually writing that many bytes to disk.
    path = tmp_path / "archive.zip"
    with open(path, "wb") as f:
        if size_bytes:
            f.seek(size_bytes - 1)
            f.write(b"\0")
    return str(path)


@pytest.mark.unit
def test_small_archive_uses_inline_code(tmp_path):
    mocks = RecordingMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)

    archive = _make_archive(tmp_path, 1024)
    Function(
        "small-fn",
        archive_location=archive,
        hash="deadbeef",
        runtime="python3.12",
        handler="app.handler",
    )
    _drain_pulumi_event_loop()

    [lambda_call] = [
        c for c in mocks.created if c.typ == "aws:lambda/function:Function"
    ]
    assert "code" in lambda_call.inputs
    assert "s3Bucket" not in lambda_call.inputs
    assert "s3Key" not in lambda_call.inputs


@pytest.mark.unit
def test_oversized_archive_without_code_bucket_raises_clear_error(tmp_path):
    mocks = RecordingMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)

    archive = _make_archive(tmp_path, DIRECT_UPLOAD_SIZE_LIMIT + 1024)
    with pytest.raises(ValueError, match="code_bucket"):
        Function(
            "oversized-fn",
            archive_location=archive,
            hash="deadbeef",
            runtime="python3.12",
            handler="app.handler",
        )


@pytest.mark.unit
def test_oversized_archive_with_code_bucket_uploads_via_s3(tmp_path):
    mocks = RecordingMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)

    archive = _make_archive(tmp_path, DIRECT_UPLOAD_SIZE_LIMIT + 1024)
    Function(
        "oversized-fn",
        archive_location=archive,
        hash="deadbeef",
        runtime="python3.12",
        handler="app.handler",
        code_bucket="my-artifacts-bucket",
    )
    _drain_pulumi_event_loop()

    [lambda_call] = [
        c for c in mocks.created if c.typ == "aws:lambda/function:Function"
    ]
    assert "code" not in lambda_call.inputs
    assert lambda_call.inputs["s3Bucket"] == "my-artifacts-bucket"
    assert lambda_call.inputs["s3Key"] == "oversized-fn/deadbeef.zip"

    [code_object_call] = [
        c for c in mocks.created if c.typ == "aws:s3/bucketObjectv2:BucketObjectv2"
    ]
    assert code_object_call.inputs["bucket"] == "my-artifacts-bucket"
