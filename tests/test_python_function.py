import pulumi
from pulumi import automation as auto
import pytest
import logging
import boto3
import json
from cloud_foundry import python_function

log = logging.getLogger(__name__)


# Define the Pulumi program
def define_pulumi_program():
    def pulumi_program():
        test_function = python_function(
            name="test-function",
            environment={
                "ENV": "production",
            },
            sources={
                "app.py": """
import os
import json

def handler(event, context):
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f\"Hello from {os.environ.get('ENV', 'unknown')}!\"
        }),
        'headers': {
            'Content-Type': 'application/json'
        }
    }
""",
            },
        )
        pulumi.export("invoke_url", test_function.function_name)
        pulumi.export("log_group_name", test_function.log_group_name)

    return pulumi_program


@pytest.fixture
def pulumi_stack():
    # Set up the Pulumi project and stack
    project_name = "cloud_foundry"
    stack_name = "test-python-function"
    pulumi_program = define_pulumi_program()

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
        # Destroy the stack
        print("Destroying Pulumi stack...")
        stack.destroy()
        print("Stack destroyed.")

        # Remove the stack
        stack.workspace.remove_stack(stack_name)


def invoke_lambda_function(function_name, payload=None):
    """
    Invokes an AWS Lambda function using boto3.

    :param function_name: The name of the Lambda function to invoke.
    :param payload: A dictionary containing the payload to send to the Lambda function.
    :return: The response from the Lambda function.
    """
    log.info("Invoking Lambda function")
    # Create a Lambda client
    lambda_client = boto3.client("lambda")

    try:
        # Invoke the Lambda function
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",  # Synchronous invocation
            Payload=json.dumps(payload or {}),
        )

        log.info(f"Lambda function invoked successfully: {response}")
        assert (
            response["StatusCode"] == 200
        ), f"Error invoking Lambda function: {response['FunctionError']}"

        log.info(f"payload: {response['Payload']}")
        # Read and decode the response payload
        response_payload = json.loads(response["Payload"].read().decode("utf-8"))

        print(f"Lambda function '{function_name}' invoked successfully.")
        return response_payload

    except Exception as e:
        print(f"Error invoking Lambda function '{function_name}': {e}")
        return None


def test_deploy_and_validate(pulumi_stack):
    stack, outputs = pulumi_stack

    # Validate the deployed service
    invoke_url = outputs.get("invoke_url").value
    assert invoke_url is not None, "Invoke URL is missing."

    # Example: Make an HTTP request to the distribution
    response = invoke_lambda_function(invoke_url)
    log.info(f"Response from Lambda function: {response}")
    assert (
        response["statusCode"] == 200
    ), f"Unexpected status code: {response['statusCode']}"
    assert "Hello from production!" in response["body"], "Unexpected response body."
