import pytest
import logging
import requests
import dotenv
from pathlib import Path

import pulumi

from cloud_foundry import python_function, rest_api
from fixture_foundry import deploy, to_localstack_url, localstack, container_network


log = logging.getLogger(__name__)
dotenv.load_dotenv()


# Define the Pulumi program
def simple_greet_api():
    def pulumi_program():
        resources_dir = Path(__file__).resolve().parent / "resources"
        greet_code = (resources_dir / "greet_api_service.py").read_text(
            encoding="utf-8"
        )

        greet_function = python_function(
            "greet-function",
            sources={
                "app.py": greet_code,  # file content, not a filesystem path
            },
        )

        greet_api = rest_api(
            "greet-api",
            specification=str(resources_dir / "greet_api_spec.yaml"),
            integrations=[
                {"path": "/greet", "method": "get", "function": greet_function}
            ],
        )

        pulumi.export("domain", greet_api.domain)

    return pulumi_program


def security_services_pulumi():
    def pulumi_program():
        security_api = SecurityAPI("security-api")

        pulumi.export("security-api-host", security_api.api.domain)
        pulumi.export("token-validator", security_api.token_validator.function_name)

    return pulumi_program


@pytest.fixture
def simple_greet_stack(request, localstack):
    teardown = request.config.getoption("--teardown").lower() == "true"
    with deploy(
        "cf-test",
        "simple-greet",
        pulumi_program=simple_greet_api(),
        localstack=localstack,
        teardown=teardown,
    ) as outputs:
        yield outputs


def test_no_auth(simple_greet_stack, localstack):
    outputs = simple_greet_stack

    # Validate the deployed service
    edge_port = localstack.get("port", 4566)
    greet_url = to_localstack_url(
        f"http://{outputs.get('domain')}/greet", edge_port=edge_port
    )
    log.info("greet_url: %s", greet_url)

    response = requests.get(greet_url, timeout=5)
    log.info("response: %s", response.text)
    assert response.status_code == 200, "Expected status code 200"
    assert (
        "Hello, World!" in response.text
    ), "Expected response body to contain 'Hello World!'"

    greet_url = f"{greet_url}?name=Bob"
    log.info("greet_url: %s", greet_url)
    response = requests.get(greet_url, timeout=5)
    log.info("response: %s", response.text)
    assert response.status_code == 200, "Expected status code 200"
    assert (
        "Hello, Bob!" in response.text
    ), "Expected response body to contain 'Hello, Bob!'"
