import pulumi
from pulumi import automation as auto
import pytest
import logging
import requests
import os
import dotenv
from cloud_foundry import python_function, rest_api
from tests.resources.security_services.security_pulumi import SecurityAPI

log = logging.getLogger(__name__)
dotenv.load_dotenv()


# Define the Pulumi program
def simple_greet_api():
    def pulumi_program():
        greet_function = python_function(
            "greet-function",
            sources={"app.py": "./tests/resources/greet_api_service.py"},
        )

        log.info(f"hosted_zone_id: {os.environ.get('HOSTED_ZONE_ID')}")
        greet_api = rest_api(
            "greet-api",
            specification="./tests/resources/greet_api_spec.yaml",
            integrations=[
                {"path": "/greet", "method": "get", "function": greet_function}
            ],
            hosted_zone_id=os.environ.get("HOSTED_ZONE_ID"),
        )

        log.info(f"domain: {vars(greet_api)}")
        pulumi.export("domain", greet_api.domain)

    return pulumi_program


def security_services_pulumi():
    def pulumi_program():
        security_api = SecurityAPI("security-api")

        pulumi.export("security-api-host", security_api.api.domain)
        pulumi.export("token-validator", security_api.token_validator.function_name)

    return pulumi_program


def deploy_stack(project_name, stack_name, pulumi_program):
    # Create or select the stack
    stack = auto.create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=pulumi_program,
    )
    try:
        # Deploy the stack
        print("Deploying Pulumi stack...")
        up_result = stack.up()
        print(f"Deployment complete: {up_result.summary.resource_changes}")

        yield stack, up_result.outputs
    finally:
        print("Destroying Pulumi stack...")
        stack.destroy()
        print("Stack destroyed.")

        stack.workspace.remove_stack(stack_name)


def deploy_pulumi_stack_no_teardown(project_name, stack_name, pulumi_program):
    # Create or select the stack
    stack = auto.create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=pulumi_program,
    )
    # Deploy the stack
    print("Deploying Pulumi stack...")
    up_result = stack.up()
    print(f"Deployment complete: {up_result.summary.resource_changes}")

    yield stack, up_result.outputs


@pytest.fixture
def simple_greet_stack():
    yield from deploy_stack("cf", "greet", simple_greet_api())


@pytest.fixture
def security_services_stack():
    yield from deploy_pulumi_stack_no_teardown(
        "cf", "security", security_services_pulumi()
    )


def test_no_auth(simple_greet_stack):
    stack, outputs = simple_greet_stack

    # Validate the deployed service
    domain = outputs.get("domain").value
    assert domain is not None, "Invoke URL is missing."

    greet_url = f"https://{domain}/greet"
    log.info(f"greet_url: {greet_url}")
    response = requests.get(greet_url)
    log.info(f"response: {response.text}")
    assert response.status_code == 200, "Expected status code 200"
    assert (
        "Hello, World!" in response.text
    ), "Expected response body to contain 'Hello World!'"

    greet_url = f"https://{domain}/greet?name=Bob"
    log.info(f"greet_url: {greet_url}")
    response = requests.get(greet_url)
    log.info(f"response: {response.text}")
    assert response.status_code == 200, "Expected status code 200"
    assert (
        "Hello, Bob!" in response.text
    ), "Expected response body to contain 'Hello World!'"


def test_security_services(security_services_stack):
    stack, outputs = security_services_stack

    # Validate the deployed service
    log.info(f"outputs: {outputs}")
    domain = outputs.get("security-api-host").value
    log.info(f"domain: {domain}")
    assert domain is not None, "Invoke URL is missing."

    # test login
    payload = {"username": "johndoe", "password": "Password123!"}
    response = requests.post(f"https://{domain}/login", json=payload)
    print("Login:", response.status_code, response.json())
    assert response.status_code == 200

    assert False
