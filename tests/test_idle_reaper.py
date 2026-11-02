"""attach_idle_reaper accepts the reaper's names as plain strings or as
Outputs (a StackReference from another project gives Outputs)."""

import asyncio

import pulumi
import pytest

from cloud_foundry.pulumi.idle_reaper import attach_idle_reaper
from cloud_foundry.pulumi.queue import queue


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
        if args.token == "aws:index/getCallerIdentity:getCallerIdentity":
            return {"accountId": "123456789012", "arn": "a", "userId": "u"}
        if args.token == "aws:index/getRegion:getRegion":
            return {"name": "us-east-1", "region": "us-east-1"}
        return {}


def _drain():
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.2))


@pytest.fixture
def mocks():
    m = RecordingMocks()
    pulumi.runtime.set_mocks(m, project="insight", stack="dev", preview=False)
    return m


@pytest.mark.unit
@pytest.mark.parametrize("wrap", [lambda v: v, pulumi.Output.from_input])
def test_reaper_names_as_str_or_output(mocks, wrap):
    inbox = queue("index-requests")
    mapping = inbox.subscribe("worker-fn")
    attach_idle_reaper(
        inbox,
        mapping,
        reaper_function_name=wrap("cep-dev-idle-esm-reaper"),
        reaper_role_name=wrap("cep-dev-idle-esm-reaper-role"),
        resource_prefix="insight-dev-index-requests",
    )
    _drain()

    targets = [
        r for r in mocks.created if r.typ == "aws:cloudwatch/eventTarget:EventTarget"
    ]
    assert len(targets) == 2
    for target in targets:
        assert target.inputs["arn"].endswith(":function:cep-dev-idle-esm-reaper")
