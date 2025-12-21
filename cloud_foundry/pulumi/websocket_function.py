# websocket_function.py

import pulumi
from typing import Union, Optional
from cloud_foundry.pulumi.function import Function
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class WebSocketFunction(Function):
    """
    A specialized Lambda function for WebSocket API route handlers.

    Extends the base Function class with WebSocket-specific features:
    - Access to connection management (DynamoDB table for connections)
    - Helper utilities for posting messages to connections
    - Pre-configured IAM policies for API Gateway management API
    """

    def __init__(
        self,
        name,
        *,
        archive_location: str = None,
        hash: str = None,
        runtime: str = None,
        handler: str = None,
        timeout: int = None,
        memory_size: int = None,
        environment: dict[str, Union[str, pulumi.Output[str]]] = None,
        policy_statements: list = None,
        vpc_config: dict = None,
        connection_table_arn: Optional[Union[str, pulumi.Output[str]]] = None,
        connection_table_name: Optional[Union[str, pulumi.Output[str]]] = None,
        api_endpoint: Optional[Union[str, pulumi.Output[str]]] = None,
        opts=None,
    ):
        """
        Initialize a WebSocket Lambda function.

        Args:
            name (str): Name of the function
            archive_location (str): Path to the Lambda deployment package
            hash (str): Hash of the deployment package for change detection
            runtime (str): Lambda runtime (e.g., python3.13)
            handler (str): Handler function path (e.g., app.handler)
            timeout (int): Function timeout in seconds
            memory_size (int): Function memory in MB
            environment (dict): Environment variables for the function
            policy_statements (list): Additional IAM policy statements
            vpc_config (dict): VPC configuration for the function
            connection_table_arn (Optional[Union[str, pulumi.Output[str]]]):
                ARN of the DynamoDB table storing WebSocket connections
            connection_table_name (Optional[Union[str, pulumi.Output[str]]]):
                Name of the DynamoDB table storing WebSocket connections
            api_endpoint (Optional[Union[str, pulumi.Output[str]]]):
                WebSocket API endpoint for posting messages to connections
            opts (pulumi.ResourceOptions): Pulumi resource options
        """
        # Prepare environment variables
        ws_environment = environment or {}

        # Add WebSocket-specific environment variables
        if connection_table_name:
            ws_environment["CONNECTION_TABLE_NAME"] = connection_table_name
        if api_endpoint:
            ws_environment["WEBSOCKET_API_ENDPOINT"] = api_endpoint

        # Prepare policy statements
        ws_policy_statements = policy_statements or []

        # Add DynamoDB permissions if connection table is provided
        if connection_table_arn:
            ws_policy_statements.extend(
                self._get_connection_table_policies(connection_table_arn)
            )

        # Add API Gateway management API permissions for posting to connections
        if api_endpoint:
            ws_policy_statements.append(self._get_api_gateway_management_policy())

        # Initialize the base Function
        super().__init__(
            name,
            archive_location=archive_location,
            hash=hash,
            runtime=runtime,
            handler=handler,
            timeout=timeout,
            memory_size=memory_size,
            environment=ws_environment,
            policy_statements=ws_policy_statements,
            vpc_config=vpc_config,
            opts=opts,
        )

    def _get_connection_table_policies(
        self, connection_table_arn: Union[str, pulumi.Output[str]]
    ):
        """
        Get IAM policy statements for DynamoDB connection table access.

        Args:
            connection_table_arn: ARN of the connection table

        Returns:
            list: IAM policy statements
        """
        return [
            {
                "Effect": "Allow",
                "Actions": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                ],
                "Resources": [connection_table_arn],
            },
            # Add permissions for GSI queries if needed
            {
                "Effect": "Allow",
                "Actions": [
                    "dynamodb:Query",
                ],
                "Resources": [pulumi.Output.concat(connection_table_arn, "/index/*")],
            },
        ]

    def _get_api_gateway_management_policy(self):
        """
        Get IAM policy statement for API Gateway Management API.

        This allows the function to post messages to WebSocket connections.

        Returns:
            dict: IAM policy statement
        """
        return {
            "Effect": "Allow",
            "Actions": [
                "execute-api:ManageConnections",
                "execute-api:Invoke",
            ],
            "Resources": ["*"],
        }
