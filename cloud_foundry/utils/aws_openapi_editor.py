# aws_openapi_editor.py

import pulumi_aws as aws
import re
from typing import Union, Dict, List, Optional
from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor

log = logger(__name__)


class AWSOpenAPISpecEditor(OpenAPISpecEditor):
    """
    A specialized OpenAPI specification editor for AWS API Gateway.
    Provides utilities for managing integrations, CORS, schema corrections, and path operations.
    """

    def __init__(self, spec: Optional[Union[Dict, str, List[str]]]):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[Dict, str, List[str]]): A dictionary containing the OpenAPI specification,
                                                a string representing YAML content, or a file path.
        """
        super().__init__(
            spec
            or {
                "openapi": "3.0.3",
                "info": {
                    "title": "API",
                    "version": "1.0.0",
                    "description": "Generated OpenAPI Spec",
                },
                "paths": {},
                "components": {"schemas": {}, "securitySchemes": {}},
            }
        )

    def add_token_validator(self, name: str, function_name: str, invoke_arn: str):
        """
        Add a Lambda token validator to the OpenAPI spec.

        Args:
            name (str): The name for the token validator.
            function_name (str): The name of the Lambda function to be used for validation.
            invoke_arn (str): The ARN of the Lambda function.
        """
        security_schemes = self.get_or_create_spec_part(
            ["components", "securitySchemes"], create=True
        )

        security_schemes[name] = {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "x-function-name": function_name,
            "x-amazon-apigateway-authtype": "custom",
            "x-amazon-apigateway-authorizer": {
                "type": "token",
                "authorizerUri": invoke_arn,
                "identitySource": "method.request.header.Authorization",
                "authorizerResultTtlInSeconds": 60,
            },
        }

    def add_user_pool_validator(self, name: str, user_pool_arns: List[str]):
        """
        Add a Cognito User Pool validator to the OpenAPI spec.

        Args:
            name (str): The name for the token validator.
            user_pool_arns (List[str]): A list of Cognito User Pool ARNs.
        """
        security_schemes = self.get_or_create_spec_part(
            ["components", "securitySchemes"], create=True
        )

        security_schemes[name] = {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "x-amazon-apigateway-authtype": "cognito_user_pools",
            "x-amazon-apigateway-authorizer": {
                "type": "cognito_user_pools",
                "providerARNs": user_pool_arns,
                "authorizerResultTtlInSeconds": 60,
            },
        }

    def add_integration(
        self, path: str, method: str, function_name: str, invoke_arn: str
    ):
        """
        Add an integration to a specific path and method in the OpenAPI spec.
        If the integration already exists, replace it with the new one.

        Args:
            path (str): The API path (e.g., "/token").
            method (str): The HTTP method (e.g., "post").
            function_name (str): The name of the Lambda function.
            invoke_arn (str): The ARN of the Lambda function to integrate with.
        """
        operation = self.get_or_create_spec_part(["paths", path, method], create=True)
        if not operation:
            log.warning(
                f"Operation for path '{path}' and method '{method}' does not exist."
            )
            return

        operation["x-function-name"] = function_name
        operation["x-amazon-apigateway-integration"] = {
            "type": "aws_proxy",
            "uri": invoke_arn,
            "httpMethod": "POST",
        }

    def process_integrations(
        self,
        integrations: list[dict],
        invoke_arns: list[str],
        function_names: list[str],
    ):
        """
        Process and add each integration to the OpenAPI spec using the resolved invoke ARNs and function names.

        Args:
            integrations (list[dict]): List of integrations defined in the configuration.
            invoke_arns (list[str]): Resolved ARNs of the integration functions.
            function_names (list[str]): Resolved function names of the integration functions.
        """
        for integration, invoke_arn, function_name in zip(
            integrations, invoke_arns, function_names
        ):
            self.add_integration(
                integration["path"], integration["method"], function_name, invoke_arn
            )

    def process_content(self, content: list[dict], credentials_arn: str):
        """
        Process and add S3 content integrations to the OpenAPI spec.

        Args:
            content (list[dict]): List of content configurations.
            credentials_arn (str): The ARN of the IAM role for accessing S3.
        """
        for item in content:
            path = item.get("path")
            bucket_name = item.get("bucket_name")
            prefix = item.get("prefix", "")
            summary = item.get("summary")
            description = item.get("description")

            uri = (
                f"arn:aws:apigateway:us-east-1:s3:path/{bucket_name}/{prefix}/{{proxy}}"
                if prefix
                else f"arn:aws:apigateway:us-east-1:s3:path/{bucket_name}/{{proxy}}"
            )

            self.get_or_create_spec_part(["paths", f"{path}/{{proxy+}}"], create=True)[
                "get"
            ] = {
                "summary": summary,
                "description": description,
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {"application/octet-stream": {}},
                    }
                },
                "x-amazon-apigateway-integration": {
                    "type": "aws",
                    "uri": uri,
                    "httpMethod": "GET",
                    "passthroughBehavior": "when_no_match",
                    "requestParameters": {
                        "integration.request.path.proxy": "method.request.path.proxy",
                    },
                    "responses": {
                        "default": {
                            "statusCode": "200",
                            "responseParameters": {
                                "method.response.header.Content-Type": "integration.response.header.Content-Type"
                            },
                        }
                    },
                    "credentials": credentials_arn,
                },
            }

    def correct_schema_names(self):
        """
        Correct schema component names to strictly alphabetic characters and update all references accordingly.
        """
        non_alphabetic_pattern = re.compile(r"[^a-zA-Z]")
        schemas = self.get_spec_part(["components", "schemas"], create=False)
        if not schemas:
            return

        renamed_schemas = {}
        for schema_name in list(schemas.keys()):
            new_schema_name = re.sub(non_alphabetic_pattern, "", schema_name)
            if new_schema_name != schema_name:
                renamed_schemas[schema_name] = new_schema_name

        for old_name, new_name in renamed_schemas.items():
            schemas[new_name] = schemas.pop(old_name)

        def update_refs(data):
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "$ref" and isinstance(value, str):
                        for old_name, new_name in renamed_schemas.items():
                            if f"#/components/schemas/{old_name}" in value:
                                data[key] = value.replace(
                                    f"#/components/schemas/{old_name}",
                                    f"#/components/schemas/{new_name}",
                                )
                    else:
                        update_refs(value)
            elif isinstance(data, list):
                for item in data:
                    update_refs(item)

        update_refs(self.openapi_spec)

    def cors_origins(self, cors_origins: List[str]):
        """
        Enable CORS for the specified origins.

        Args:
            cors_origins (List[str]): A list of allowed origins for CORS.
        """
        paths = self.get_or_create_spec_part(["paths"], True)
        for path in paths:
            paths[path]["options"] = {
                "responses": {
                    "200": {
                        "description": "CORS preflight response",
                        "headers": {
                            "Access-Control-Allow-Origin": {"type": "string"},
                            "Access-Control-Allow-Methods": {"type": "string"},
                            "Access-Control-Allow-Headers": {"type": "string"},
                        },
                    },
                },
                "x-amazon-apigateway-integration": {
                    "responses": {
                        "default": {
                            "statusCode": "200",
                            "responseParameters": {
                                "method.response.header.Access-Control-Allow-Methods": "'DELETE,GET,HEAD,OPTIONS,PATCH,POST,PUT'",
                                "method.response.header.Access-Control-Allow-Headers": "'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token'",
                                "method.response.header.Access-Control-Allow-Origin": f"'{','.join(cors_origins)}'",
                            },
                        },
                    },
                    "type": "mock",
                },
            }

    def prefix_paths(self, prefix: str):
        """
        Add a prefix to all paths in the OpenAPI spec.

        Args:
            prefix (str): The prefix to apply to all paths (e.g., "/v1").
        """
        paths = self.get_spec_part(["paths"], create=False)
        if not paths:
            return

        updated_paths = {}
        for path, operations in paths.items():
            new_path = f"{prefix.rstrip('/')}/{path.lstrip('/')}"
            updated_paths[new_path] = operations

        self.openapi_spec["paths"] = updated_paths

    def remove_unintegrated_operations(self):
        """
        Remove operations from the OpenAPI spec that do not have an integration.
        If a path has no operations left after removal, the path itself is also removed.
        """
        paths = self.get_spec_part(["paths"], create=False)
        if not paths:
            return

        for path, methods in list(paths.items()):
            for method, operation in list(methods.items()):
                if "x-amazon-apigateway-integration" not in operation:
                    del methods[method]

            if not methods:
                del paths[path]
