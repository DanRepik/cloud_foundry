"""
Tests for the Queue component (cloud_foundry.pulumi.queue).

Covers two things added alongside project_slug: that resource_id() (and
therefore an opted-in project_slug) actually reaches the generated queue
names, and that the receive_wait_time passthrough added for long-polling
consumers lands on the main queue's receiveWaitTimeSeconds input without
touching the DLQ.

These use pulumi's mock runtime (no AWS credentials or network access
required), following the same pattern as tests/test_rest_api_gateway_role.py.
"""

import asyncio

import pulumi
import pytest

from cloud_foundry.pulumi.queue import queue


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:sqs:us-east-1:123456789012:{args.name}")
        outputs.setdefault(
            "id", f"https://sqs.us-east-1.amazonaws.com/123456789012/{args.name}"
        )
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


def _find(mocks, resource_type, name):
    return next(r for r in mocks.created if r.typ == resource_type and r.name == name)


@pytest.mark.unit
def test_queue_and_dlq_names_use_resource_id(mocks):
    queue("ingestion-pipeline", visibility_timeout=900, message_retention=345600)
    _drain_pulumi_event_loop()

    dlq = _find(mocks, "aws:sqs/queue:Queue", "ingestion-pipeline-dlq")
    main = _find(mocks, "aws:sqs/queue:Queue", "ingestion-pipeline")

    assert dlq.inputs["name"] == "cep-dev-ingestion-pipeline-dlq"
    assert main.inputs["name"] == "cep-dev-ingestion-pipeline"


@pytest.mark.unit
def test_receive_wait_time_reaches_main_queue_only(mocks):
    queue("ingestion-pipeline", receive_wait_time=20)
    _drain_pulumi_event_loop()

    dlq = _find(mocks, "aws:sqs/queue:Queue", "ingestion-pipeline-dlq")
    main = _find(mocks, "aws:sqs/queue:Queue", "ingestion-pipeline")

    assert main.inputs["receiveWaitTimeSeconds"] == 20
    assert "receiveWaitTimeSeconds" not in dlq.inputs


@pytest.mark.unit
def test_receive_wait_time_defaults_to_short_polling(mocks):
    queue("ingestion-pipeline")
    _drain_pulumi_event_loop()

    main = _find(mocks, "aws:sqs/queue:Queue", "ingestion-pipeline")

    assert main.inputs["receiveWaitTimeSeconds"] == 0
