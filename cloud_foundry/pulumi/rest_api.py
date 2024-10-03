import pulumi
import pulumi_aws as aws
from typing import Optional

from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor
from cloud_foundry.utils.logger import logger
from cloud_foundry.pulumi.function import Function

log = logger(__name__)

class RestAPI(pulumi.ComponentResource):
    rest_api: Optional[aws.apigateway.RestApi] = None
    rest_api_id: pulumi.Output[str]

    def __init__(self, name, body: str, integrations: list[dict] = None, opts=None):
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.editor = OpenAPISpecEditor(body)

        # Collect all invoke_arns from integrations before proceeding
        all_invoke_arns = [
            integration["function"].invoke_arn for integration in self.integrations
        ]

        # Wait for all invoke_arns to resolve and then build the API
        def build_api(invoke_arns):
            return self._build(invoke_arns)

        # Set up the output that will store the REST API ID
        self.rest_api_id = pulumi.Output.all(*all_invoke_arns).apply(build_api).apply(
            lambda _: self.rest_api.id
        )

        # Register the outputs for the component
        self.register_outputs({"rest_api_id": self.rest_api_id})

    def _add_integration(
        self, path: str, method: str, function_name: str, invoke_arn: str
    ):
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

    def _process_integrations(self, invoke_arns: list[str]):
        # Add each integration to the OpenAPI spec using the resolved invoke_arns
        log.info("process integrations")
        for integration, invoke_arn in zip(self.integrations, invoke_arns):
            log.info(f"add integration path: {integration['path']}")
            self._add_integration(
                integration["path"],
                integration["method"],
                integration["function"].function_name,
                invoke_arn,
            )

    def _build(self, invoke_arns: list[str]) -> pulumi.Output[None]:
        log.info(f"running build")

        self._process_integrations(invoke_arns)
        self.rest_api = aws.apigateway.RestApi(
            self.name,
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-rest-api",
            body=self.editor.to_yaml(),
            opts=pulumi.ResourceOptions(parent=self),
        )
        log.info(f"spec: {self.editor.to_yaml()}")

        log.info("running build deployment")
        deployment = aws.apigateway.Deployment(
            f"{self.name}-deployment",
            rest_api=self.rest_api.id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        log.info(f"running build stage")
        aws.apigateway.Stage(
            f"{self.name}-stage",
            rest_api=self.rest_api.id,
            deployment=deployment.id,
            stage_name=self.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        log.info(f"running build register outputs")
        # Return an output indicating completion
        return pulumi.Output.from_input(None)

def rest_api(name: str, body: str, integrations: list[dict]):
    log.info(f"rest_api name: {name}")
    rest_api_instance = RestAPI(name, body=body, integrations=integrations)
    # Export the REST API ID using the output registered in the component
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    return rest_api_instance
