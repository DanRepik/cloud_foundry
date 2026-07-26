"""
Regression tests for CDN.get_origins().

Two bugs fixed here:
1. f-strings like f"{name}-{origin["name"]}" use unescaped double quotes
   nested inside a double-quoted f-string, which is only valid on Python
   3.12+ (PEP 701). pyproject.toml declares requires-python >=3.9, so this
   module could not even be imported on 3.9-3.11.
2. The "rest_api" origin branch for a plain aws.apigateway.RestApi (as
   opposed to this package's own RestAPI component) accessed
   origin.rest_api.name / origin.rest_api.id - but `origin` is a plain
   dict, not an object with a `.rest_api` attribute, so this raised
   AttributeError immediately. It should read from the already-extracted
   `rest_api` local variable instead.

These tests use pulumi's mock runtime (no AWS/network access required)
and monkeypatch the CustomGatewayDomain class used by get_origins() so
the test only has to verify the right values are resolved and passed
through, without also mocking the full ACM/Route53 certificate
validation chain that CustomGatewayDomain itself performs.
"""

import asyncio

import pulumi
import pulumi_aws as aws
import pytest

import cloud_foundry.pulumi.cdn as cdn_module
from cloud_foundry.pulumi.cdn import CDN


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("id", args.name + "_id")
        outputs.setdefault(
            "arn", f"arn:aws:apigateway:us-east-1::/restapis/{args.name}"
        )
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain_pulumi_event_loop():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def cdn_instance():
    pulumi.runtime.set_mocks(RecordingMocks(), preview=False)

    cdn = CDN.__new__(CDN)
    pulumi.ComponentResource.__init__(
        cdn, "cloud_foundry:pulumi:CDN", "test-cdn", {}, None
    )
    cdn.hosted_zone_id = "Z123456"
    cdn.subdomain = "test"
    return cdn


class FakeGatewayDomain:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.domain_name = "resolved.example.com"


@pytest.mark.unit
def test_get_origins_with_plain_rest_api_resolves_from_local_variable(
    cdn_instance, monkeypatch
):
    calls = []

    def fake_gateway_domain(name, **kwargs):
        resolved = {"name": name}
        kwargs["rest_api_id"].apply(lambda v: resolved.__setitem__("rest_api_id", v))
        kwargs["stage_name"].apply(lambda v: resolved.__setitem__("stage_name", v))
        calls.append(resolved)
        return FakeGatewayDomain(name, **kwargs)

    monkeypatch.setattr(cdn_module, "CustomGatewayDomain", fake_gateway_domain)

    plain_rest_api = aws.apigateway.RestApi("plain-rest-api")

    cdn_origins, caches, target_origin_id = cdn_instance.get_origins(
        "test-cdn", [{"name": "api", "rest_api": plain_rest_api}]
    )

    _drain_pulumi_event_loop()

    assert len(calls) == 1
    assert calls[0]["stage_name"] == "plain-rest-api"
    assert calls[0]["rest_api_id"] == "plain-rest-api_id"
    assert len(cdn_origins) == 1
