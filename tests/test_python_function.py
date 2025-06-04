import pulumi
from pulumi import automation as auto
import pytest
import logging
import boto3
import json
import cloud_foundry

log = logging.getLogger(__name__)


# Define the Pulumi program
def simple_function_deployment():
    def pulumi_program():
        test_function = cloud_foundry.python_function(
            name="test-function",
            environment={
                "ENV": "production",
            },
            sources={
                "app.py": """
import json

def handler(event, _):
    name = (event.get("queryStringParameters") or {}).get("name", "World")

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Hello, {name}!"}),
        "headers": {"Content-Type": "application/json"},
    }
""",
            },
        )
        pulumi.export("invoke_url", test_function.function_name)
        pulumi.export("log_group_name", test_function.log_group_name)

    return pulumi_program


def deploy_stack(project_name, stack_name, pulumi_program):
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


def deploy_stack_no_teardown(project_name, stack_name, pulumi_program):
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


@pytest.fixture(scope="module")
def simple_function_stack():
    yield from deploy_stack("cf-test", "simple-func", simple_function_deployment())


def test_simple(simple_function_stack):
    stack, outputs = simple_function_stack

    # Validate the deployed service
    invoke_url = outputs.get("invoke_url").value
    assert invoke_url is not None, "Invoke URL is missing."

    # Create a Lambda client
    lambda_client = boto3.client("lambda")

    # Example payload
    payload = {"queryStringParameters": {"name": "World"}}

    # Invoke the Lambda function
    response = lambda_client.invoke(
        FunctionName=invoke_url,
        InvocationType="RequestResponse",  # Synchronous invocation
        Payload=json.dumps(payload),
    )
    log.info(f"Lambda response: {response}")
    assert (
        response["StatusCode"] == 200
    ), f"Error invoking Lambda function: {response.get('FunctionError')}"

    # Read and decode the response payload
    response_payload = json.loads(response["Payload"].read().decode("utf-8"))
    log.info(f"Response payload: {response_payload}")
    assert "Hello, World!" in response_payload["body"], "Unexpected response body."


def test_with_param(simple_function_stack):
    stack, outputs = simple_function_stack

    # Validate the deployed service
    invoke_url = outputs.get("invoke_url").value
    assert invoke_url is not None, "Invoke URL is missing."

    # Create a Lambda client
    lambda_client = boto3.client("lambda")

    # Invoke the Lambda function
    # To pass the name as a query string parameter, update the payload accordingly
    payload = {"queryStringParameters": {"name": "Alice"}}

    # test with a query string parameter
    response = lambda_client.invoke(
        FunctionName=invoke_url,
        InvocationType="RequestResponse",  # Synchronous invocation
        Payload=json.dumps(payload),
    )

    assert (
        response["StatusCode"] == 200
    ), f"Error invoking Lambda function: {response.get('FunctionError')}"

    # Read and decode the response payload
    response_payload = json.loads(response["Payload"].read().decode("utf-8"))
    log.info(f"Response payload: {response_payload}")
    assert "Hello, Alice!" in response_payload["body"], "Unexpected response body."
