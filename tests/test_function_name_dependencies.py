"""Components that call or grant on a cloud_foundry Function must take its
name from the Lambda resource's Output, not Function.function_name (a plain
string). Only the Output makes Pulumi create the function first: with the
string, postgres_schema's Invocation ran in parallel with the function's
creation and failed with "Function not found".

The mocks give each Lambda a deployed name that differs from
Function.function_name, so these pass only when the Output is used.
"""

import asyncio
import zipfile

import pulumi
import pytest

import cloud_foundry.pulumi.python_function as python_function_module


class RecordingMocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.created = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.created.append(args)
        outputs = dict(args.inputs)
        if args.typ == "aws:lambda/function:Function":
            outputs["name"] = "deployed-" + args.name
        outputs.setdefault("name", args.name)
        outputs.setdefault("arn", f"arn:aws:mock:us-east-1:123456789012:{args.name}")
        outputs.setdefault("result", "{}")
        return [args.name + "_id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        if "getPolicyDocument" in args.token:
            return {"json": "{}"}
        if "getCallerIdentity" in args.token:
            return {"accountId": "123456789012"}
        if "getRegion" in args.token:
            return {"name": "us-east-1", "region": "us-east-1"}
        return {}


class FakeArchiveBuilder:
    """Skips staging sources and pip installs; points at a tiny real zip."""

    path = None

    def __init__(self, **_kwargs):
        pass

    def hash(self):
        return "hash"

    def location(self):
        return FakeArchiveBuilder.path


def _drain():
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.3))


@pytest.fixture
def mocks(monkeypatch, tmp_path):
    archive = tmp_path / "code.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("app.py", "def handler(e, c): return {}\n")
    FakeArchiveBuilder.path = str(archive)
    monkeypatch.setattr(python_function_module, "PythonArchiveBuilder", FakeArchiveBuilder)
    m = RecordingMocks()
    pulumi.runtime.set_mocks(m, project="insight", stack="dev", preview=False)
    return m


def _one(mocks, typ):
    (resource,) = [r for r in mocks.created if r.typ == typ]
    return resource


@pytest.mark.unit
def test_postgres_schema_invokes_the_created_function(mocks):
    from cloud_foundry.pulumi.postgres_schema import postgres_schema

    postgres_schema(
        "insight-db",
        cluster_arn="arn:aws:rds:us-east-1:123456789012:cluster:c",
        master_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:m",
        database="candidate_evidence",
        role_name="insight_app",
    )
    _drain()

    function = _one(mocks, "aws:lambda/function:Function")
    invocation = _one(mocks, "aws:lambda/invocation:Invocation")
    assert invocation.inputs["functionName"] == "deployed-" + function.name


@pytest.mark.unit
def test_schedule_grants_on_the_created_function(mocks):
    from cloud_foundry.pulumi.python_function import python_function
    from cloud_foundry.pulumi.schedule import schedule

    worker = python_function("worker", sources={"app.py": "x"})
    schedule("tick", schedule_expression="rate(1 hour)", function=worker)
    _drain()

    function = _one(mocks, "aws:lambda/function:Function")
    permission = _one(mocks, "aws:lambda/permission:Permission")
    assert permission.inputs["function"] == "deployed-" + function.name
