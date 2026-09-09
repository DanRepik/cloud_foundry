"""
Tests for the Topic component (cloud_foundry.pulumi.topic).

Covers that resource_id() (and therefore an opted-in project_slug) reaches
the generated topic name, and that the topic_name property added for
callers that need the deployed AWS name (rather than the plain logical
name shadowed by self.name) resolves correctly.

These use pulumi's mock runtime (no AWS credentials or network access
required), following the same pattern as tests/test_rest_api_gateway_role.py.
"""

import asyncio

import pulumi
import pytest

from cloud_foundry.pulumi.topic import topic


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:sns:us-east-1:123456789012:{args.name}")
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain_pulumi_event_loop():
    """Give pulumi's Output.apply callbacks a chance to run."""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def mocks():
    m = RecordingMocks()
    pulumi.runtime.set_mocks(m, project="cep", stack="dev", preview=False)
    return m


@pytest.mark.unit
def test_topic_name_uses_resource_id(mocks):
    t = topic("ingestion-events", display_name="Ingestion Events Topic")
    _drain_pulumi_event_loop()

    created = next(r for r in mocks.created if r.typ == "aws:sns/topic:Topic")
    assert created.inputs["name"] == "cep-dev-ingestion-events"
    assert created.inputs["displayName"] == "Ingestion Events Topic"

    captured = {}
    t.topic_name.apply(lambda n: captured.setdefault("name", n))
    _drain_pulumi_event_loop()

    assert captured["name"] == "cep-dev-ingestion-events"


@pytest.mark.unit
def test_topic_name_output_differs_from_logical_name_attribute(mocks):
    t = topic("ingestion-events")
    _drain_pulumi_event_loop()

    # self.name is the plain logical name callers pass in; topic_name is
    # the deployed AWS name. They're intentionally different attributes so
    # neither shadows the other.
    assert t.name == "ingestion-events"

    captured = {}
    t.topic_name.apply(lambda n: captured.setdefault("name", n))
    _drain_pulumi_event_loop()

    assert captured["name"] == "cep-dev-ingestion-events"
