# rest_api.py

import pulumi
import pulumi_aws as aws
from typing import Optional, Union
from cloud_foundry.utils.logger import logger, write_logging_file
from cloud_foundry.utils.localstack import is_localstack_deployment
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor

log = logger(__name__)

class RestAPI(pulumi.ComponentResource):
    """
    A Pulumi component resource that creates and manages an AWS API Gateway REST API
    with Lambda integrations and token validators.
    
    This class allows you to create a REST API, attach Lambda functions to path operations 
    (integrations), and associate token validators for authentication.

    Attributes:
        rest_api (Optional[aws.apigateway.RestApi]): The AWS API Gateway REST API resource.
        rest_api_id (pulumi.Output[str]): The ID of the created REST API.
    """

    rest_api: Optional[aws.apigateway.RestApi] = None
    rest_api_id: pulumi.Output[str] = None  # Ensure rest_api_id is defined

    def __init__(
        self,
        name: str,
        body: Union[str, list[str]],
        integrations: list[dict] = None,
        token_validators: list[dict] = None,
        opts=None,
    ):
        """
        Initialize the RestAPI component resource.

        Args:
            name (str): The name of the REST API.
            body (Union[str, list[str]]): The OpenAPI specification for the API.
                                          This can be a string or a list of strings (YAML or JSON).
            integrations (list[dict], optional): A list of integrations that define the Lambda functions
                                                 attached to path operations.
            token_validators (list[dict], optional): A list of token validators that define authentication functions.
            opts (pulumi.ResourceOptions, optional): Additional options for the resource.
        """
        super().__init__("cloud_forge:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.token_validators = token_validators or []
        self.editor = AWSOpenAPISpecEditor(body)

        # Collect all invoke ARNs and function names from integrations and token validators before proceeding
        integration_arns = [integration["function"].invoke_arn for integration in self.integrations]
        integration_function_names = [integration["function"].function_name for integration in self.integrations]

        token_validator_arns = [validator["function"].invoke_arn for validator in self.token_validators]
        token_validator_function_names = [validator["function"].function_name for validator in self.token_validators]

        # Wait for all invoke ARNs and function names to resolve and then build the API
        def build_api(invoke_arns, function_names):
            """
            Build the API by processing the OpenAPI spec, adding integrations, and creating the REST API resource.

            Args:
                invoke_arns (list[str]): A list of Lambda function ARNs for integrations and token validators.
                function_names (list[str]): A list of Lambda function names for integrations and token validators.

            Returns:
                pulumi.Output[str]: The REST API ID.
            """
            self._build(invoke_arns, function_names)
            return self.rest_api.id

        # Set up the output that will store the REST API ID
        all_arns = integration_arns + token_validator_arns
        all_function_names = integration_function_names + token_validator_function_names
        # Pulumi will resolve both ARNs and function names before proceeding to build the API
        self.rest_api_id = pulumi.Output.all(*all_arns, *all_function_names).apply(
            lambda arns_and_names: build_api(arns_and_names[:len(all_arns)], arns_and_names[len(all_arns):])
        )

    def _build(self, invoke_arns: list[str], function_names: list[str]) -> pulumi.Output[None]:
        """
        Build the REST API and create the necessary integrations, token validators, and deployment.

        Args:
            invoke_arns (list[str]): The list of Lambda function ARNs.
            function_names (list[str]): The list of Lambda function names.

        Returns:
            pulumi.Output[None]: Returns an empty output as the build process completes.
        """
        log.info(f"running build")

        # Process integrations and token validators using the provided ARNs and function names
        self.editor.process_integrations(
            self.integrations, invoke_arns[:len(self.integrations)], function_names[:len(self.integrations)]
        )
        self.editor.process_token_validators(
            self.token_validators, invoke_arns[len(self.integrations):], function_names[len(self.integrations):]
        )

        # Write the updated OpenAPI spec to a file for logging or debugging
        write_logging_file(f"{self.name}.yaml", self.editor.to_yaml()) 

        # Create the RestApi resource in AWS API Gateway
        self.rest_api = aws.apigateway.RestApi(
            self.name,
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-rest-api",
            body=self.editor.to_yaml(),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add permissions for API Gateway to invoke the Lambda functions
        self._create_lambda_permissions(function_names)

        # Create the API Gateway deployment and stage
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

    def _create_lambda_permissions(self, function_names: list[str]):
        """
        Create permissions for each Lambda function so that API Gateway can invoke them.

        Args:
            function_names (list[str]): The list of Lambda function names to set permissions for.
        """
        permission_names = []
        for function_name in function_names:
            if function_name in permission_names:
                continue
            log.info(f"Creating permission for function: {function_name}")
            aws.lambda_.Permission(
                f"{function_name}-lambda-permission",
                action="lambda:InvokeFunction",
                function=function_name,
                principal="apigateway.amazonaws.com",
                source_arn=self.rest_api.execution_arn.apply(lambda arn: f"{arn}/*/*"),
                opts=pulumi.ResourceOptions(parent=self),
            )
            permission_names.append(function_name)

    def _get_function_names_from_spec(self) -> list[str]:
        """
        Extract function names from the OpenAPI specification using OpenAPISpecEditor.

        Returns:
            list[str]: A list of function names found in the OpenAPI specification.
        """
        return self.editor.get_function_names()

def rest_api(
    name: str,
    body: Union[str, list[str]],
    integrations: list[dict] = None,
    token_validators: list[dict] = None,
):
    """
    Helper function to create and configure a REST API using the RestAPI component.

    Args:
        name (str): The name of the REST API.
        body (str): The OpenAPI specification file path.
        integrations (list[dict], optional): A list of integrations that define the Lambda functions
                                             attached to path operations.
        token_validators (list[dict], optional): A list of token validators that define authentication functions.

    Returns:
        RestAPI: The created REST API component resource.
    """
    log.info(f"rest_api name: {name}")
    rest_api_instance = RestAPI(
        name, body=body, integrations=integrations, token_validators=token_validators
    )
    log.info("built rest_api")

    # Export the REST API ID and host as outputs
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    host =  (
        "execute-api.localhost.localstack.cloud:4566"
        if is_localstack_deployment()
        else "execute-api.us-east-1.amazonaws.com"
    )
    pulumi.export(f"{name}-host",
        rest_api_instance.rest_api_id.apply( lambda api_id: f"{api_id}.{host}/{name}")
    )

    log.info("return rest_api")
    return rest_api_instance
