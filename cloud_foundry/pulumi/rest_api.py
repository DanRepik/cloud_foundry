# rest_api.py

import pulumi
import pulumi_aws as aws
from typing import Optional

from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor
from cloud_foundry.utils.logger import logger
from cloud_foundry.pulumi.function import Function

log = logger(__name__)

class RestAPI(pulumi.ComponentResource):
    rest_api: aws.apigateway.RestApi

    def __init__(self, name, body: str, integrations: list[dict] = None, opts=None):
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)
        self.name = name
        self.editor = OpenAPISpecEditor(body)

        if integrations:
            self._gather_and_add_integrations(integrations)
        else:
            # Build the API immediately if no integrations are provided
            self.build()

    def _add_integration(self, path: str, method: str, function_name: str, invoke_arn: str):
        log.info(f"invoke_arn: {invoke_arn}")
        self.editor.add_operation_attribute(
            path=path,
            method=method,
            attribute="x-function-name",
            value=function_name,
        )
        self.editor.add_operation_attribute(
            path=path,
            method=method,
            attribute="x-amazon-apigateway-integration",
            value={
                "type": "aws_proxy",
                "uri": invoke_arn,
                "httpMethod": "POST",
            },
        )

    def _gather_and_add_integrations(self, integrations: list[dict]):
        # Collect all invoke_arns from integrations before proceeding
        all_invoke_arns = [integration["function"].invoke_arn for integration in integrations]

        # Wait for all invoke_arns to resolve
        pulumi.Output.all(*all_invoke_arns).apply(lambda invoke_arns: self._process_integrations(integrations, invoke_arns))

    def _process_integrations(self, integrations: list[dict], invoke_arns: list[str]):
        # Add each integration to the OpenAPI spec using the resolved invoke_arns
        log.info("process integrations")
        for integration, invoke_arn in zip(integrations, invoke_arns):
            log.info(f"add integration path: {integration['path']}")
            self._add_integration(
                integration["path"],
                integration["method"],
                integration["function"].function_name,
                invoke_arn,
            )

        # Now that all integrations are added, build the API
        log.info(f"running build")
        self.build()

    def build(self):
        self.rest_api = aws.apigateway.RestApi(
            f"{self.name}-rest-api",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-rest-api",
            body=self.editor.to_yaml(),
            opts=pulumi.ResourceOptions(parent=self),
        )

        deployment = aws.apigateway.Deployment(
            f"{self.name}-deployment",
            rest_api=self.rest_api.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        aws.apigateway.Stage(
            f"{self.name}-stage",
            rest_api=self.rest_api.id,
            deployment=deployment.id,
            stage_name=self.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        pulumi.export(f"{self.name}-id", self.rest_api.id)
        self.register_outputs({"id": self.rest_api.id})

    def id(self) -> pulumi.Output[str]:
        return self.rest_api.id


def rest_api(name: str, body: str, integrations: list[dict]):
    log.info(f"rest_api name: {name}")
    rest_api = RestAPI(name, body=body, integrations=integrations)
