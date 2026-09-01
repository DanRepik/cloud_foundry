import asyncio
import os
import pytest

DEFAULT_IMAGE = "localstack/localstack:latest"
DEFAULT_SERVICES = "logs,iam,lambda,secretsmanager,apigateway,cloudwatch,s3"

os.environ["PULUMI_BACKEND_URL"] = "file://~"


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
