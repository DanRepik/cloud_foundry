"""
Regression test: RestAPI._create_rest_api()'s S3 spec export must actually
write the spec content.

Previously, aws.s3.BucketObject(key, bucket=bucket_name, ...) was created
with no `content=`/`source=` argument, so export_api="s3://bucket/key"
created an empty object in S3 - the generated OpenAPI spec was silently
never written, unlike the file-export branch a few lines below which
correctly writes self.editor.yaml.

Uses pulumi's mock runtime (no AWS/network access needed). _build_spec,
_create_lambda_permissions, and _create_cognito_permissions are stubbed
out since they require a full set of integrations/token validators to
exercise - this test targets only the S3 export branch.
"""

import asyncio

import pulumi
import pytest

from cloud_foundry.pulumi.rest_api import RestAPI
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain_pulumi_event_loop():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.2))


def _simple_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/hello": {
                "get": {
                    "summary": "Say hello",
                    "responses": {"200": {"description": "A greeting"}},
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
    }


@pytest.mark.unit
def test_s3_export_writes_spec_content(monkeypatch):
    mocks = RecordingMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)

    monkeypatch.setattr(
        RestAPI,
        "_build_spec",
        lambda self, invoke_arns: setattr(self, "api_spec", self.editor.yaml),
    )
    monkeypatch.setattr(RestAPI, "_create_lambda_permissions", lambda self: None)
    monkeypatch.setattr(
        RestAPI, "_create_cognito_permissions", lambda self, invoke_arns: None
    )

    api = RestAPI.__new__(RestAPI)
    pulumi.ComponentResource.__init__(
        api, "cloud_foundry:apigw:RestAPI", "test-api", None, None
    )
    api.name = "test-api"
    api.editor = AWSOpenAPISpecEditor(_simple_spec())
    api.export_api = "s3://my-bucket/spec.yaml"

    api._create_rest_api([])
    _drain_pulumi_event_loop()

    bucket_object = next(
        r for r in mocks.created if r.typ == "aws:s3/bucketObject:BucketObject"
    )

    assert bucket_object.inputs.get("bucket") == "my-bucket"
    content = bucket_object.inputs.get("content")
    assert content, "expected the S3 object to carry the spec content"
    assert "hello" in content
