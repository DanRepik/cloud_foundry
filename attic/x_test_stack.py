# tests/test_stack.py

import pulumi
import pulumi_aws as aws
import pulumi.automation as auto
import os
import shutil
from typing import Callable, Dict, Optional, Tuple

# Type alias for the pulumi program function
PulumiProgram = Callable[[], None]


def pulumi_stack_up(
    stack_name: str, project_name: str, pulumi_program: PulumiProgram
) -> Tuple[auto.Stack, Dict[str, auto.OutputValue]]:
    """
    Sets up and runs a Pulumi stack using the specified program.

    Args:
        stack_name (str): The name of the stack.
        project_name (str): The name of the project.
        pulumi_program (PulumiProgram): The inline function defining the Pulumi program.

    Returns:
        Tuple[auto.Stack, Dict[str, auto.OutputValue]]: The deployed Pulumi stack and its outputs.
    """

    # Define the local backend for the stack state
    local_backend_path = os.path.join(os.getcwd(), "temp", "pulumi-local-backend")

    # Set the Pulumi backend using an environment variable
    os.environ["PULUMI_BACKEND_URL"] = f"file://{local_backend_path}"

    # Ensure the backend directory exists
    if not os.path.exists(local_backend_path):
        os.makedirs(local_backend_path)

    # Set the stack to use the local filesystem backend
    workspace_opts = auto.LocalWorkspaceOptions(
        work_dir=os.getcwd(),  # Current working directory
        project_settings=auto.ProjectSettings(
            name=project_name,
            runtime="python",
        ),
    )

    # Create or select a Pulumi stack with the local backend
    stack = auto.create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=pulumi_program,
        opts=workspace_opts,
    )

    # Set configuration options for the stack
    stack.set_config("aws:region", auto.ConfigValue(value="us-west-2"))

    # Deploy the stack and get the outputs
    up_res = stack.up()

    # Return the stack and its outputs
    return stack, up_res.outputs


def pulumi_stack_down(stack):
    # Teardown (destroy the stack after the test)
    stack.destroy()

    # Optionally remove the local backend directory if you want to clean up the state
    local_backend_path = os.path.join(os.getcwd(), "temp", "pulumi-local-backend")
    if os.path.exists(local_backend_path):
        shutil.rmtree(local_backend_path)


_localstack_provider: Optional[aws.Provider] = None


def localstack_provider() -> aws.Provider:
    global _localstack_provider
    if not _localstack_provider:
        _localstack_provider = aws.Provider(
            "localstack",
            skip_credentials_validation=True,  # Ensure AWS credential validation is skipped
            skip_metadata_api_check=True,  # Ensure AWS metadata API validation is skipped
            s3_use_path_style=True,
            region="us-east-2",
            endpoints=[
                aws.ProviderEndpointArgs(s3="http://localhost.localstack.cloud:4566")
            ],
        )
    print(f"localstack_provider: {_localstack_provider}")
    return _localstack_provider


# Example of a test using the common function
def test_bucket_creation() -> None:
    """
    Test function to create an S3 bucket using Pulumi and LocalStack.
    """

    # Define the Pulumi program for the test
    def pulumi_program() -> None:
        # Create an S3 bucket using the LocalStack provider
        bucket = aws.s3.Bucket(
            "my-bucket",
            versioning={"enabled": True},
            opts=pulumi.ResourceOptions(provider=localstack_provider()),
        )

        # Export the bucket's ARN (Amazon Resource Name)
        # pulumi.export("bucket_arn", bucket.arn)
        pulumi.export("bucket_arn", "bucket.arn")

    stack = None
    try:
        # Call the common function to deploy the stack
        stack, outputs = pulumi_stack_up("local_stack", "test_project", pulumi_program)

        # Assert that the bucket ARN was created and is part of the outputs
        assert "bucket_arn" in outputs
        assert outputs["bucket_arn"].value.startswith("arn:aws:s3")
        print(f"S3 Bucket ARN: {outputs['bucket_arn'].value}")
    finally:
        if stack:
            pulumi_stack_down(stack)
