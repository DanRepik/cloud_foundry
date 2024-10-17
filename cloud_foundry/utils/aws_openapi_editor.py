# aws_openapi_editor.py

from typing import Union, Dict, List
from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor

log = logger(__name__)


class AWSOpenAPISpecEditor(OpenAPISpecEditor):
    def __init__(self, spec: Union[Dict, str]):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[Dict, str]): A dictionary containing the OpenAPI specification
                                     or a string representing YAML content or a file path.
        """
        super().__init__(spec)

    def add_token_authorizer(self, name: str, function_name: str, authentication_invoke_arn: str):
        # Use get_or_create_spec_part to ensure 'components' and 'securitySchemes' exist
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
                "authorizerUri": authentication_invoke_arn,
                "identityValidationExpression": "^Bearer [-0-9a-zA-Z._]*$",
                "identitySource": "method.request.header.Authorization",
                "authorizerResultTtlInSeconds": 60,
            },
        }

    def process_authorizers(self, authorizers: list[dict], invoke_arns: list[str], function_names: list[str]):
        """
        Process and add each authorizer to the OpenAPI spec using the resolved invoke_arns and function names.

        Args:
            authorizers (list[dict]): List of authorizers defined in the configuration.
            invoke_arns (list[str]): Resolved ARNs of the authorizer functions.
            function_names (list[str]): Resolved function names of the authorizer functions.
        """
        log.info(f"process authorizers: {invoke_arns}")
        for authorizer, invoke_arn, function_name in zip(authorizers, invoke_arns, function_names):
            log.info(f"add authorizer: {authorizer['name']}")
            if authorizer["type"] == "token":
                self.add_token_authorizer(authorizer["name"], function_name, invoke_arn)

    def _add_integration(self, path: str, method: str, function_name: str, invoke_arn: str):
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

    def process_integrations(self, integrations: list[dict], invoke_arns: list[str], function_names: list[str]):
        """
        Process and add each integration to the OpenAPI spec using the resolved invoke_arns and function names.

        Args:
            integrations (list[dict]): List of integrations defined in the configuration.
            invoke_arns (list[str]): Resolved ARNs of the integration functions.
            function_names (list[str]): Resolved function names of the integration functions.
        """
        log.info(f"process integrations: {invoke_arns}")
        for integration, invoke_arn, function_name in zip(integrations, invoke_arns, function_names):
            log.info(f"add integration path: {integration['path']}")
            self._add_integration(
                integration["path"],
                integration["method"],
                function_name,
                invoke_arn,
            )

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
