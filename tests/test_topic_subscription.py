"""Tests for subscribe_queue_to_topic, Topic.subscribe's filter policy and
Queue.subscribe_to_topic, under pulumi's mock runtime."""

import asyncio
import json

import pulumi
import pytest

from cloud_foundry.pulumi.queue import queue
from cloud_foundry.pulumi.topic import topic
from cloud_foundry.pulumi.topic_subscription import subscribe_queue_to_topic


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:mock:us-east-1:123456789012:{args.name}")
        outputs.setdefault("id", f"https://sqs.example/{args.name}")
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain():
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def mocks():
    m = RecordingMocks()
    pulumi.runtime.set_mocks(m, project="cep", stack="dev", preview=False)
    return m


def _of_type(mocks, typ):
    return [r for r in mocks.created if r.typ == typ]


@pytest.mark.unit
def test_imported_topic_with_body_filter(mocks):
    inbox = queue("index-requests")
    subscribe_queue_to_topic(
        "index-events",
        topic_arn="arn:aws:sns:us-east-1:123456789012:cep-dev-ingestion-events",
        queue=inbox,
        filter_policy={"operation": ["artifact_version_created"]},
        filter_policy_scope="MessageBody",
    )
    _drain()

    (sub,) = _of_type(mocks, "aws:sns/topicSubscription:TopicSubscription")
    assert sub.name == "cep-dev-index-events-sub"
    assert sub.inputs["topic"].endswith("cep-dev-ingestion-events")
    assert json.loads(sub.inputs["filterPolicy"]) == {
        "operation": ["artifact_version_created"]
    }
    assert sub.inputs["filterPolicyScope"] == "MessageBody"

    (policy,) = _of_type(mocks, "aws:sqs/queuePolicy:QueuePolicy")
    statement = json.loads(policy.inputs["policy"])["Statement"][0]
    assert statement["Condition"]["ArnEquals"]["aws:SourceArn"].endswith(
        "cep-dev-ingestion-events"
    )


@pytest.mark.unit
def test_no_filter_policy_by_default(mocks):
    inbox = queue("index-requests")
    inbox.subscribe_to_topic("arn:aws:sns:us-east-1:123456789012:events")
    _drain()

    (sub,) = _of_type(mocks, "aws:sns/topicSubscription:TopicSubscription")
    assert sub.name == "cep-dev-index-requests-topic-sub"
    assert "filterPolicy" not in sub.inputs
    assert "rawMessageDelivery" not in sub.inputs


@pytest.mark.unit
def test_topic_subscribe_keeps_resource_names(mocks):
    """Topic.subscribe delegates but must keep its existing resource names,
    or deployed stacks would replace their subscriptions."""
    inbox = queue("ai-requests")
    events = topic("ingestion-events")
    events.subscribe(inbox, filter_policy={"operation": ["x"]})
    _drain()

    names = {r.name for r in mocks.created}
    assert "cep-dev-ingestion-events-ai-requests-policy" in names
    assert "cep-dev-ingestion-events-ai-requests-sub" in names
    (sub,) = _of_type(mocks, "aws:sns/topicSubscription:TopicSubscription")
    assert json.loads(sub.inputs["filterPolicy"]) == {"operation": ["x"]}
