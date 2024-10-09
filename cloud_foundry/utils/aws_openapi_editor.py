# aws_openapi_editor.py

import yaml
import json
import os
from typing import Union, Dict

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

    def add_token_authorizer(self, name: str, authentication_invoke_arn: str):
        # Use get_or_create_spec_part to ensure 'components' and 'securitySchemes' exist
        security_schemes = self.get_or_create_spec_part(
            ["components", "securitySchemes"], create=True
        )

        security_schemes[name] = {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "x-amazon-apigateway-authtype":"custom",
            "x-amazon-apigateway-authorizer": {
                "type": "token",
                "authorizerUri": authentication_invoke_arn,
                "identityValidationExpression": "^Bearer [-0-9a-zA-Z._]*$",
                "identitySource": "method.request.header.Authorization",
                "authorizerResultTtlInSeconds": 60,
            },
        }

    def process_authorizers(self, authorizers: list[dict], invoke_arns: list[str]):
        # Add each integration to the OpenAPI spec using the resolved invoke_arns
        log.info(f"process authorizers: {invoke_arns}")
        for authorizer, invoke_arn in zip(authorizers, invoke_arns):
            log.info(f"add authorizers path: {authorizer['name']}")
            if authorizer["type"] == "token":
                self.add_token_authorizer(authorizer["name"], invoke_arn)

    def _add_integration(
        self, path: str, method: str, function_name: str, invoke_arn: str
    ):
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

    def process_integrations(self, integrations: list[dict], invoke_arns: list[str]):
        # Add each integration to the OpenAPI spec using the resolved invoke_arns
        log.info(f"process integrations {invoke_arns}")
        for integration, invoke_arn in zip(integrations, invoke_arns):
            log.info(f"add integration path: {integration['path']}")
            self._add_integration(
                integration["path"],
                integration["method"],
                integration["function"].function_name,
                invoke_arn,
            )
