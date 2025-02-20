# rest_api.py

import json
import pulumi
import pulumi_aws as aws
from typing import Optional, Union
from cloud_foundry.utils.logger import logger, write_logging_file
from cloud_foundry.utils.localstack import is_localstack_deployment
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor
from .api_waf import RestAPIFirewall, GatewayRestApiWAF
from .rest_api_logging_role import ApiGatewayLoggingRole

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
        path_operations: list[dict] = None,
        content: list[dict] = None,
        token_validators: list[dict] = None,
        firewall: Optional[RestAPIFirewall] = None,
        logging: Optional[bool] = False,
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
        super().__init__("cloudy_foundry:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.token_validators = token_validators or []
        self.content = content or []
        self.editor = AWSOpenAPISpecEditor(body)
        self.firewall = firewall
        self.logging = logging

        # Collect all invoke ARNs and function names from integrations and token validators before proceeding
        integration_arns = [
            integration["function"].invoke_arn for integration in self.integrations
        ]
        integration_function_names = [
            integration["function"].function_name for integration in self.integrations
        ]

        token_validator_arns = [
            validator["function"].invoke_arn for validator in self.token_validators
        ]
        token_validator_function_names = [
            validator["function"].function_name for validator in self.token_validators
        ]

        gateway_role = self._get_gateway_role()
        log.info(f"gateway_role: {gateway_role}")

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
        all_arns = integration_arns + token_validator_arns + [gateway_role.arn]
        all_function_names = integration_function_names + token_validator_function_names
        # Pulumi will resolve both ARNs and function names before proceeding to build the API
        self.rest_api_id = pulumi.Output.all(*all_arns, *all_function_names).apply(
            lambda arns_and_names: build_api(
                arns_and_names[: len(all_arns)], arns_and_names[len(all_arns) :]
            )
        )

    def _build(
        self, invoke_arns: list[str], function_names: list[str]
    ) -> pulumi.Output[None]:
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
            self.integrations,
            invoke_arns[: len(self.integrations)],
            function_names[: len(self.integrations)],
        )
        self.editor.process_token_validators(
            self.token_validators,
            invoke_arns[len(self.integrations) :],
            function_names[len(self.integrations) : -1],
        )
        self.editor.process_content(self.content, invoke_arns[-1])

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
        if self.logging:
            log.info("setting up logging")

            stage = aws.apigateway.Stage(
                f"{self.name}-stage",
                rest_api=self.rest_api.id,
                deployment=deployment.id,
                stage_name=self.name,
                opts=pulumi.ResourceOptions(parent=self),
                access_log_settings={
                    "destinationArn": aws.cloudwatch.LogGroup(
                        f"{self.name}-log-group",
                        retention_in_days=7,
                        opts=pulumi.ResourceOptions(parent=self),
                    ).arn,
                    "format": json.dumps(
                        {
                            "requestId": "$context.requestId",
                            "ip": "$context.identity.sourceIp",
                            "caller": "$context.identity.caller",
                            "user": "$context.identity.user",
                            "requestTime": "$context.requestTime",
                            "httpMethod": "$context.httpMethod",
                            "resourcePath": "$context.resourcePath",
                            "status": "$context.status",
                            "protocol": "$context.protocol",
                            "responseLength": "$context.responseLength",
                        }
                    ),
                },
            )
        else:
            log.info(f"running build stage")
            stage = aws.apigateway.Stage(
                f"{self.name}-stage",
                rest_api=self.rest_api.id,
                deployment=deployment.id,
                stage_name=self.name,
                opts=pulumi.ResourceOptions(parent=self),
            )

        if self.firewall:
            log.info("setting up firewall")
            waf = GatewayRestApiWAF(f"{self.name}-waf", self.firewall)
            """
            web_acl_association = aws.wafv2.WebAclAssociation(
                f"{self.name}-waf-association",
                resource_arn=stage.arn,
                web_acl_arn=waf.arn)
            """

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

    def _get_gateway_role(self):
        """
        Grants API Gateway access to the specified S3 buckets.

        Args:
            bucket_names (list[str]): List of S3 bucket names that the API should access.
        """

        def generate_s3_policy(buckets):
            log.info(f"buckets: {buckets}")
            resources = []
            for bucket in buckets:
                resources.append(f"arn:aws:s3:::{bucket}")
                resources.append(f"arn:aws:s3:::{bucket}/*")
            log.info(f"resources: {resources}")

            return json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["s3:GetObject", "s3:ListBucket"],
                            "Resource": resources,
                        }
                    ],
                }
            )

        bucket_names = [
            item["bucket_name"] for item in self.content if "bucket_name" in item
        ]
        log.info(f"bucket_names: {bucket_names}")
        # Define policy allowing API Gateway access to the given S3 buckets
        s3_policy = aws.iam.Policy(
            f"{self.name}-s3-access-policy",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-s3-access-policy",
            description=f"Policy allowing API Gateway to access S3 buckets for {self.name}",
            policy=pulumi.Output.all(*bucket_names).apply(
                lambda buckets: generate_s3_policy(buckets)
            ),
        )

        # Create IAM Role if it does not exist
        api_gateway_role = aws.iam.Role(
            f"{self.name}-api-gw-role",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-api-gw-role",
            assume_role_policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "apigateway.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )

        # Attach the policy to the role
        aws.iam.RolePolicyAttachment(
            f"{self.name}-s3-access-attachment",
            policy_arn=s3_policy.arn,
            role=api_gateway_role.name,
        )

        log.info(f"S3 access policy attached successfully. {api_gateway_role}")
        return api_gateway_role


def rest_api(
    name: str,
    body: Union[str, list[str]] = None,
    integrations: list[dict] = None,
    token_validators: list[dict] = None,
    path_operations: list[dict] = None,
    content: list[dict] = None,
    firewall: RestAPIFirewall = None,
    logging: Optional[bool] = False,
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
    rest_api_instance = RestAPI(**vars())
    log.info("built rest_api")

    # Export the REST API ID and host as outputs
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    host = (
        "execute-api.localhost.localstack.cloud:4566"
        if is_localstack_deployment()
        else "execute-api.us-east-1.amazonaws.com"
    )
    pulumi.export(
        f"{name}-host",
        rest_api_instance.rest_api_id.apply(lambda api_id: f"{api_id}.{host}/{name}"),
    )

    log.info("return rest_api")
    return rest_api_instance
