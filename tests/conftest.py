import os
import pytest

DEFAULT_IMAGE = "localstack/localstack:latest"
DEFAULT_SERVICES = "logs,iam,lambda,secretsmanager,apigateway,cloudwatch,s3"

os.environ["PULUMI_BACKEND_URL"] = "file://~"


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
