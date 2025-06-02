# Streamlined Infrastructure Testing: Using Pulumi Automation for Unit Testing Deployments

I have been working on Cloud Foundry, an open source infrastructure library that provides a curated set of components that can be readily assembled into cloud-centric applications. While IAC tools like Tofu and Pulumi handle the deployment of elemental components, Cloud Foundry provides a higher level of abstraction. For example, when creating a function in Cloud Foundry, all that is needed is the location of the source code; the library then handles the details of packaging and deploying the function, along with appropriate logging and security. When associating a function with an API, Cloud Foundry handles the integration between the two. By automating the assembly of application components, Cloud Foundry allows organizations to avoid getting mired in infrastructure code and focus on business needs, delivering software quickly and reliably.

To achieve the "quickly and reliably" value proposition of the library, thorough testing is essential. For this type of software, testing typically involves deploying the infrastructure, verifying the deployment artifacts, running functional tests, and finally tearing down the deployment. While scripts or Makefiles can automate this process, they often become unwieldy and error-prone. Scripts may fail, resources can be left orphaned, and when tests go awry, developers are forced to manually intervene and clean up the environment, requiring a thorough understanding of the system's internals.

Testing infrastructure deployments has always been somewhat problematic.

With the increasing complexity of infrastructure management, ensuring that deployments are flawless has become crucial. Traditional testing methods often fall short when it comes to infrastructure as code. Enter Pulumi Automation, a powerful tool that allows you to programmatically control deployments and integrate them into your testing pipeline. This article will guide you through the process of setting up unit tests for your infrastructure.

Pulumi is an infrastructure as code platform that enables developers to write, deploy, and manage cloud resources using real programming languages. Pulumi Automation API extends Pulumi's capabilities, allowing programmers to orchestrate deployments programmatically, fitting perfectly within automated pipelines.

## Why Unit Test Deployments?

- **Prevent Misconfigurations:** Catch configuration errors before they impact production.
- **Ensure Idempotency:** Verify that deployments can be consistently applied without side effects.
- **Validate Outputs:** Ensure that deployments produce the expected outcomes.

## Organizing Infrastructure Tests with Pulumi and Pytest

The test code is organized into three main components for infrastructure testing:

* **Test Deployment Program:** Defines the infrastructure to test (e.g., a `python_function` as a cloud resource).
* **Pytest Fixture:** Manages the Pulumi stack lifecycle; deploys the infrastructure resources before the test, yields stack and outputs, then destroys and cleans up after the test. Ensures each test runs in a clean environment without any residual or orphaned resources afterwards.
* **Test Function:** Receives the deployed stack and outputs, validates the deployment (e.g., invokes the function and checks the response), and uses assertions to confirm expected behavior.

This structure separates concerns, making the tests modular, reliable, and easy to maintain. The deployment logic, resource management, and validation are each handled in their own dedicated sections of the code.

## Define the Test Deployment

The deployment program defines the infrastructure that will be tested during the unit test process.

In this example, the infrastructure consists of a simple Python function deployed as a cloud resource using the Cloud Foundry `python_function` component. The function's code is provided inline within the test script, but the `python_function` component is flexible and can also accept code from external files or entire folders, making it suitable for more complex applications.

Exporting outputs like the invoke URL and log group name allows the test function to access the deployment's resources directly.

```python
import pulumi
import cloud_foundry

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
```

## Define the Pytest Fixture

The deployment of infrastructure is managed by a pytest fixture (for example, `simple_greet_stack`). This fixture manages the deployment of the test infrastructure with the following process:

* The Pulumi stack is created or selected.
* The stack is deployed (`stack.up()`), and outputs are collected.
* The fixture then yields to the test function, providing outputs from the deployed infrastructure.
* After the test function completes, execution resumes after the yield in the fixture.
* The `finally` block ensures the stack is destroyed (`stack.destroy()`) and removed from the workspace, cleaning up all resources.

Managing deployment and teardown of infrastructure is a recurring process in infrastructure testing. To avoid duplicating this logic, a reusable helper function, `deploy_stack`, encapsulates the process. This keeps the tests concise and focused on validation, while ensuring consistent and reliable resource management.

```python
import pytest
from pulumi import automation as auto

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
```

With the helper function, the pytest fixture can be written as:

```python
@pytest.fixture
def simple_function_stack():
    yield from deploy_stack("cf-test", "simple-func",
           simple_function_deployment())
```

## The Test Function

The test function leverages the pytest fixture to receive the deployed Pulumi stack and its outputs. From the outputs, it extracts the function's invoke URL that is needed to send requests to the deployed Lambda function.

The `boto3` library is used to invoke the function directly, passing any required payload. The response from the Lambda invocation is then checked for expected status codes and output content using assertions.

This validates that the infrastructure was deployed correctly and that the function behaves and operates as intended, all within an automated test that is isolated and repeatable thanks to the fixture's setup and teardown logic.

```python
import boto3
import json

def test_simple_function(pulumi_stack):
    stack, outputs = pulumi_stack

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
    assert (
        response["StatusCode"] == 200
    ), f"Error invoking Lambda function: {response.get('FunctionError')}"

    # Read and decode the response payload
    response_payload = json.loads(response["Payload"].read().decode("utf-8"))
    assert "Hello, World!" in response_payload["body"], "Unexpected response body."
```

## Testing without Teardowns

During development, it can be beneficial to skip the automatic teardown of deployment resources. By keeping the stack deployed, Pulumi only updates the changes made to the infrastructure, significantly speeding up the development cycle. Avoiding teardowns is especially beneficial for deployments involving resources like CDNs, which can be slow to provision from scratch. Additionally, leaving resources running allows you to directly inspect and debug deployed infrastructure, making it easier to diagnose issues and verify behavior before automating full teardown in your final test workflow.

> **Warning:** Skipping teardown can lead to orphaned resources and unexpected cloud costs if not managed carefully. Always ensure you clean up resources manually or switch back to teardown mode before merging code or running tests in CI environments.

Once development work is complete, switching the test to use the helper with teardown and rerunning the test will clean up the cloud resources.

The helper function implementation is much simpler since the essential change is to remove the `finally` block from the code. For clarity, here is an example of a fixture using the no-teardown helper:

```python
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

@pytest.fixture
def simple_function_stack_no_teardown():
    yield from deploy_stack_no_teardown("cf-test", "simple-func",
           simple_function_deployment())
```

## Conclusion

In conclusion, using Pulumi Automation with pytest creates a robust framework for unit testing cloud infrastructure. Separating deployment, resource management, and validation keeps tests modular and maintainable, while helper functions and fixtures simplify setup and teardown, reducing manual cleanup and the risk of orphaned resources. This approach accelerates the development process, improves reliability, and ensures your infrastructure behaves as expected, helping you catch issues early and keep your cloud projects clean as you build and deploy new features.
