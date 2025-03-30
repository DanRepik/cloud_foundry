# aws_openapi_editor.py

import pulumi_aws as aws
import json
import re
from typing import Union, Dict, List, Optional
from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor

log = logger(__name__)


class AWSOpenAPISpecEditor(OpenAPISpecEditor):
    def __init__(self, spec: Optional[Union[Dict, str, List[str]]]):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[Dict, str]): A dictionary containing the OpenAPI specification
                                     or a string representing YAML content or a file path.
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

    def add_token_validator(
        self,
        name: str,
        function_name: str,
        invoke_arn: str,
    ):
        """
        Add a Lambda token validator to the OpenAPI spec.

        Args:
            name (str): The name for the token validator.
            function_name (str): The name of the Lambda function to be used for validation.
            authentication_invoke_arn (str): The ARN of the Lambda function.
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

    def add_user_pool_validator(
        self,
        name: str,
        user_pool_arns: List[str],
    ):
        """
        Add a Cognito User Pool validator to the OpenAPI spec.

        Args:
            name (str): The name for the token validator.
            user_pools (List[str]): A list of Cognito User Pool ARNs.
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

        Args:
            path (str): The API path (e.g., "/token").
            method (str): The HTTP method (e.g., "post").
            function_name (str): The name of the Lambda function.
            invoke_arn (str): The ARN of the Lambda function to integrate with.
        """
        self.add_operation_attribute(
            path=path,
            method=method,
            attribute="x-function-name",
            value=function_name,
        )
        self.add_operation_attribute(
            path=path,
            method=method,
            attribute="x-amazon-apigateway-integration",
            value={
                "type": "aws_proxy",
                "uri": invoke_arn,
                "httpMethod": "POST",
            },
        )

    def process_integrations(
        self,
        integrations: list[dict],
        invoke_arns: list[str],
        function_names: list[str],
    ):
        """
        Process and add each integration to the OpenAPI spec using the resolved invoke_arns and function names.

        Args:
            integrations (list[dict]): List of integrations defined in the configuration.
            invoke_arns (list[str]): Resolved ARNs of the integration functions.
            function_names (list[str]): Resolved function names of the integration functions.
        """
        for integration, invoke_arn, function_name in zip(
            integrations, invoke_arns, function_names
        ):
            self._add_integration(
                integration["path"],
                integration["method"],
                function_name,
                invoke_arn,
            )

    def process_content(self, content: list[dict], credentials_arn: str):
        for item in content:
            path = item.get("path")
            bucket_name = item.get("bucket_name")
            object_key = item.get("object_key")
            prefix = item.get("prefix", "")
            summary = item.get("summary")
            description = item.get("description")

            log.info(f"path: {path}")
            if prefix:
                uri = f"arn:aws:apigateway:us-east-1:s3:path/{bucket_name}/{prefix}/{{proxy}}"
            else:
                uri = f"arn:aws:apigateway:us-east-1:s3:path/{bucket_name}/{{proxy}}"

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
                    "loggingLevel": "INFO",
                    "dataTraceEnabled": True,
                },
            }

    def get_function_names(self) -> list[str]:
        """
        Return a list of all 'x-function-name' attributes in the OpenAPI spec.

        Returns:
            List[str]: A list of function names found in the OpenAPI spec.
        """
        function_names = []
        paths = self.get_spec_part(["paths"])
        log.info(f"path: {paths}")

        if paths:
            for _, methods in paths.items():
                for _, operation in methods.items():
                    function_name = operation.get("x-function-name")
                    if function_name:
                        function_names.append(function_name)

        security_schemes = self.get_spec_part(["components", "securitySchemes"])
        log.info(f"security: {security_schemes}")
        if security_schemes:
            for _, scheme in security_schemes.items():
                function_name = scheme.get("x-function-name")
                if function_name:
                    function_names.append(function_name)

        log.info(f"function_names: {function_names}")

        return function_names

    def correct_schema_names(self):
        """
        Correct schema component names to strictly alphabetic characters and update all references accordingly.

        This function renames any schema components that have non-alphabetic characters and ensures all $ref
        references in the OpenAPI specification are updated to match the renamed components.

        Returns:
            None
        """
        # Regex pattern to match non-alphabetic characters
        non_alphabetic_pattern = re.compile(r"[^a-zA-Z]")

        schemas = self.get_spec_part(["components", "schemas"], create=False)
        if not schemas:
            log.warning("No schemas found in the OpenAPI spec.")
            return

        # Map old schema names to new schema names (strictly alphabetic)
        renamed_schemas = {}
        for schema_name in list(schemas.keys()):
            # Generate new schema name by replacing non-alphabetic characters with empty string
            new_schema_name = re.sub(non_alphabetic_pattern, "", schema_name)
            if new_schema_name != schema_name:
                renamed_schemas[schema_name] = new_schema_name

        # Apply schema renaming
        for old_name, new_name in renamed_schemas.items():
            schemas[new_name] = schemas.pop(old_name)
            log.info(f"Renamed schema '{old_name}' to '{new_name}'")

        # Now, update all $ref references in the OpenAPI spec to match the new schema names
        def update_refs(data):
            """Recursively update all $ref occurrences to match the renamed schema components."""
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

        # Update references in the entire OpenAPI spec
        update_refs(self.openapi_spec)

    def enable_origin(self, allow_origin):
        log.info(f"enable_origin: {allow_origin}")
        paths = self.get_or_create_spec_part(["paths"], True)
        for path in paths:
            log.info(f"path: {path}")
            paths[path]["options"] = {
                "consumes": ["application/json"],
                "produces": ["application/json"],
                "responses": {
                    "200": {
                        "description": f"200 response",
                        "schema": {
                            "type": "object",
                        },
                        "headers": {
                            "Access-Control-Allow-Origin": {
                                "type": "string",
                            },
                            "Access-Control-Allow-Methods": {
                                "type": "string",
                            },
                            "Access-Control-Allow-Headers": {
                                "type": "string",
                            },
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
                                "method.response.header.Access-Control-Allow-Origin": "'*'",
                            },
                            "responseTemplates": {
                                "application/json": "",
                            },
                        },
                    },
                    "requestTemplates": {
                        "application/json": f'{{"statusCode": 200}}',
                    },
                    "passthroughBehavior": "when_no_match",
                    "type": "mock",
                },
            }

        self.get_or_create_spec_part([])["x-amazon-apigateway-cors"] = {
            "allowOrigins": ["*"],
            "allowCredentials": True,
            "allowMethods": ["GET", "POST", "OPTIONS", "PUT", "PATCH", "DELETE"],
            "allowHeaders": [
                "Origin",
                "X-Requested-With",
                "Content-Type",
                "Accept",
                "Authorization",
            ],
        }
