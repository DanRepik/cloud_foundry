import asyncio
import os
import pytest

# Pinned rather than :latest: LocalStack moved to a unified image in March
# 2026 (see https://localstack.cloud/2026-updates) that requires a Pro
# license/LOCALSTACK_AUTH_TOKEN even for these Community-tier services,
# causing every LocalStack-backed test to fail with "License activation
# failed" in CI. 4.14.0 (2026-02-26) is the last release before that
# change and needs no token -- verified locally: all of DEFAULT_SERVICES
# below come up as "available" under "edition": "community".
DEFAULT_IMAGE = "localstack/localstack:4.14.0"
DEFAULT_SERVICES = "logs,iam,lambda,secretsmanager,apigateway,cloudwatch,s3"

os.environ["PULUMI_BACKEND_URL"] = "file://~"
# The local file backend's secrets manager requires a passphrase; these are
# ephemeral, disposable test stacks with no real secrets to protect, so an
# empty one is fine. Without this, stack creation fails outright.
os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    # Python's asyncio stopped auto-creating a loop for the main thread when
    # none is set (get_event_loop() now raises instead). pulumi.runtime
    # .set_mocks() constructs an asyncio.Future() internally and expects one
    # to already exist, so tests calling set_mocks() outside any async
    # context need a loop pre-installed.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("localstack")
    group.addoption(
        "--teardown",
        action="store",
        default="true",
        help="Whether to not tear down the LocalStack container after tests (default: false)",
    )
    group.addoption(
        "--use-localstack",
        action="store",
        default="true",
        help="Whether to use LocalStack for tests (default: true)",
    )
    group.addoption(
        "--localstack-image",
        action="store",
        default=DEFAULT_IMAGE,
        help="Docker image to use for LocalStack (default: localstack/localstack:latest)",
    )
    group.addoption(
        "--localstack-services",
        action="store",
        default=DEFAULT_SERVICES,
        help="Comma-separated list of LocalStack services to start (default: secretsmanager)",
    )
    group.addoption(
        "--localstack-timeout",
        action="store",
        type=int,
        default=90,
        help="Seconds to wait for LocalStack to become healthy (default: 90)",
    )
    group.addoption(
        "--localstack-port",
        action="store",
        type=int,
        default=0,
        help="Port for LocalStack edge service (default: 4566)",
    )
