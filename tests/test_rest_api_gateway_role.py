"""
Regression tests for RestAPI._get_gateway_role().

Previously, aws.iam.RolePolicyAttachment was created without a `role=`
argument (a required field on the underlying pulumi_aws resource), so any
RestAPI(..., content=[...]) deployment using S3-backed content
integration would fail at `pulumi up` with a missing-argument error.

Separately, the S3 access policy granted access to the entire bucket even
when a content mapping specified a `prefix`, over-granting access on
buckets shared across multiple prefixes/tenants.

These tests use pulumi's mock runtime (no AWS credentials or network
access required) to drive RestAPI._get_gateway_role() directly and
inspect the resource arguments that would be sent to the provider.
"""

import asyncio
import json

import pulumi
import pytest

from cloud_foundry.pulumi.rest_api import RestAPI


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:iam::123456789012:role/{args.name}")
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain_pulumi_event_loop():
    """Give pulumi's Output.apply callbacks a chance to run."""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def gateway_role_api():
    mocks = RecordingMocks()
    pulumi.runtime.set_mocks(mocks, preview=False)

    api = RestAPI.__new__(RestAPI)
    pulumi.ComponentResource.__init__(
        api, "cloud_foundry:apigw:RestAPI", "test-api", None, None
    )
    return api, mocks


def _find(mocks, resource_type):
    return next(r for r in mocks.created if r.typ == resource_type)


@pytest.mark.unit
def test_gateway_role_attaches_s3_policy_to_role(gateway_role_api):
    api, mocks = gateway_role_api
    api.name = "test-api"
    api.content = [{"bucket_name": "my-bucket", "path": "/static"}]

    api._get_gateway_role()
    _drain_pulumi_event_loop()

    attachment = _find(mocks, "aws:iam/rolePolicyAttachment:RolePolicyAttachment")
    assert attachment.inputs.get("role")
    assert attachment.inputs.get("policyArn")


@pytest.mark.unit
def test_gateway_role_scopes_s3_grant_to_prefix(gateway_role_api):
    api, mocks = gateway_role_api
    api.name = "test-api"
    api.content = [
        {"bucket_name": "shared-bucket", "prefix": "tenant-a", "path": "/static"}
    ]

    api._get_gateway_role()
    _drain_pulumi_event_loop()

    policy = _find(mocks, "aws:iam/policy:Policy")
    resources = json.loads(policy.inputs["policy"])["Statement"][0]["Resource"]

    assert resources == ["arn:aws:s3:::shared-bucket/tenant-a/*"]


@pytest.mark.unit
def test_gateway_role_grants_whole_bucket_without_prefix(gateway_role_api):
    api, mocks = gateway_role_api
    api.name = "test-api"
    api.content = [{"bucket_name": "my-bucket", "path": "/static"}]

    api._get_gateway_role()
    _drain_pulumi_event_loop()

    policy = _find(mocks, "aws:iam/policy:Policy")
    resources = json.loads(policy.inputs["policy"])["Statement"][0]["Resource"]

    assert "arn:aws:s3:::my-bucket" in resources
    assert "arn:aws:s3:::my-bucket/*" in resources
