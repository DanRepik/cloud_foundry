# rest_api.py

import pulumi
import pulumi_aws as aws
from typing import Optional, Union

from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor

log = logger(__name__)

class RestAPI(pulumi.ComponentResource):
    rest_api: Optional[aws.apigateway.RestApi] = None
    rest_api_id: pulumi.Output[str] = None  # Ensure rest_api_id is defined

    def __init__(
        self,
        name,
        body: Union[str, list[str]],
        integrations: list[dict] = None,
        authorizers: list[dict] = None,
        opts=None,
    ):
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.authorizers = authorizers or []
        self.editor = AWSOpenAPISpecEditor(body)

        # Collect all invoke_arns from integrations before proceeding
        integration_arns = [
            integration["function"].invoke_arn for integration in self.integrations
        ]
        log.info(f"integration_arns: {integration_arns}")

        if not isinstance(integration_arns, list):
            integration_arns = [integration_arns]

        # Collect all invoke_arns from authorizers before proceeding
        authorizer_arns = [
            authorizer["function"].invoke_arn for authorizer in self.authorizers
        ]
        log.info(f"authorizer_arns: {authorizer_arns}")

        if not isinstance(authorizer_arns, list):
            authorizer_arns = [authorizer_arns]


        # Wait for all invoke_arns to resolve and then build the API
        def build_api(invoke_arns):
            self._build(invoke_arns)
            log.info(f"returning from build_api {self.rest_api}")
            result = self.rest_api.id
            log.info(f"self.rest_api: {isinstance( result, pulumi.Output)}")
            return result

        # Set up the output that will store the REST API ID
        all_arns = integration_arns + authorizer_arns
        self.rest_api_id = pulumi.Output.all(*all_arns).apply(build_api)

    def _build(self, invoke_arns: list[str]) -> pulumi.Output[None]:
        log.info(f"running build")

        # Process integrations
        self.editor.process_integrations(
            self.integrations, invoke_arns[: len(self.integrations)]
        )
        self.editor.process_authorizers(
            self.authorizers, invoke_arns[len(self.integrations) :]
        )

        log.info(f"spec: {self.editor.to_yaml()}")

        # Create the RestApi
        self.rest_api = aws.apigateway.RestApi(
            self.name,
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-rest-api",
            body=self.editor.to_yaml(),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add permissions for API Gateway to invoke the Lambda functions
        function_names = self._get_function_names_from_spec()
        for function_name in function_names:
            aws.lambda_.Permission(
                f"{function_name}-api-gateway-permission",
                action="lambda:InvokeFunction",
                function=function_name,
                principal="apigateway.amazonaws.com",
                source_arn=self.rest_api.execution_arn.apply(lambda arn: f"{arn}/*/*"),
                opts=pulumi.ResourceOptions(parent=self),
            )

        # Create the deployment and stage
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

        # Register the output for the REST API ID
        self.register_outputs({"rest_api_id": self.rest_api.id})

        log.info("returning from build")
        return pulumi.Output.from_input(None)

    def _get_function_names_from_spec(self) -> list[str]:
        """
        Extract function names from the OpenAPI specification using OpenAPISpecEditor.
        """
        function_names = []
        paths = self.editor.openapi_spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                # Retrieve the function name from the operation's attributes
                function_name = operation.get("x-function-name")
                if function_name:
                    function_names.append(function_name)
        return function_names

def rest_api(
    name: str,
    body: str,
    integrations: list[dict] = None,
    authorizers: list[dict] = None,
):
    log.info(f"rest_api name: {name}")
    rest_api_instance = RestAPI(
        name, body=body, integrations=integrations, authorizers=authorizers
    )
    log.info("built rest_api")
    # Export the REST API ID using the output registered in the component
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    log.info("return rest_api")
    return rest_api_instance
