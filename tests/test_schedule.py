"""Tests for the Schedule component, under pulumi's mock runtime."""

import asyncio
import json

import pulumi
import pulumi_aws as aws
import pytest

from cloud_foundry.pulumi.schedule import schedule


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:mock:us-east-1:123456789012:{args.name}")
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        return {}


def _drain():
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def mocks():
    m = RecordingMocks()
    pulumi.runtime.set_mocks(m, project="insight", stack="dev", preview=False)
    return m


def _one(mocks, typ):
    (resource,) = [r for r in mocks.created if r.typ == typ]
    return resource


@pytest.mark.unit
def test_function_target_with_input_and_permission(mocks):
    worker = aws.lambda_.Function(
        "worker",
        role="arn:aws:iam::123456789012:role/r",
        runtime="python3.12",
        handler="app.handler",
    )
    schedule(
        "index-reconcile",
        schedule_expression="rate(1 hour)",
        function=worker,
        input={"operation": "index_reconcile"},
    )
    _drain()

    rule = _one(mocks, "aws:cloudwatch/eventRule:EventRule")
    assert rule.inputs["name"] == "insight-dev-index-reconcile"
    assert rule.inputs["scheduleExpression"] == "rate(1 hour)"
    assert rule.inputs["state"] == "ENABLED"

    target = _one(mocks, "aws:cloudwatch/eventTarget:EventTarget")
    assert json.loads(target.inputs["input"]) == {"operation": "index_reconcile"}

    permission = _one(mocks, "aws:lambda/permission:Permission")
    assert permission.inputs["principal"] == "events.amazonaws.com"


@pytest.mark.unit
def test_target_arn_without_permission(mocks):
    schedule(
        "daily-poll",
        schedule_expression="cron(15 11 * * ? *)",
        target_arn="arn:aws:sns:us-east-1:123456789012:discovery",
        enabled=False,
    )
    _drain()

    assert (
        _one(mocks, "aws:cloudwatch/eventRule:EventRule").inputs["state"] == "DISABLED"
    )
    assert not [r for r in mocks.created if r.typ == "aws:lambda/permission:Permission"]


@pytest.mark.unit
def test_exactly_one_target_required(mocks):
    with pytest.raises(ValueError):
        schedule("bad", schedule_expression="rate(1 hour)")
