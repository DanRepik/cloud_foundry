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

    This class uses AWSOpenAPISpecEditor to process the OpenAPI spec by attaching
    Lambda integrations, Cognito or Lambda token validators, and S3 content integrations.
    """

    rest_api: Optional[aws.apigateway.RestApi] = None
    rest_api_id: pulumi.Output[str] = None  # The REST API identifier

    def __init__(
        self,
        name: str,
        body: Optional[Union[str, list[str]]] = None,
        integrations: Optional[list[dict]] = None,
        cors_origins: Optional[str] = False,
        content: Optional[list[dict]] = None,
        token_validators: Optional[list[dict]] = None,
        firewall: Optional[RestAPIFirewall] = None,
        logging: Optional[bool] = False,
        path_prefix: Optional[str] = None,
        opts=None,
    ):
        """
        Initialize the RestAPI component resource.

        Args:
            name (str): The name of the REST API.
            body (Optional[Union[str, list[str]]]): The OpenAPI specification for the API.
            integrations (Optional[list[dict]], optional): List of integrations defining Lambda functions for path operations.
            token_validators (Optional[list[dict]], optional): List of token validators for authentication.
            cors_origins (Optional[str], optional): If truthy, enables CORS in the API spec.
            content (Optional[list[dict]], optional): List of static content definitions (e.g. S3 integrations).
            firewall (Optional[RestAPIFirewall], optional): Firewall configuration.
            logging (Optional[bool], optional): Enable API Gateway stage logging.
            path_prefix (Optional[str], optional): A prefix to prepend to all API paths.
            opts (pulumi.ResourceOptions, optional): Additional resource options.
        """
        super().__init__("cloud_foundry:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.token_validators = token_validators or []
        self.content = content or []
        self.editor = AWSOpenAPISpecEditor(body)
        self.firewall = firewall
        self.logging = logging
        self.path_prefix = path_prefix

        write_logging_file(f"{self.name}-pre.yaml", self.editor.yaml)

        log.info(f"cors_origins: {cors_origins}")
        if cors_origins:
            self.editor.cors_origins(cors_origins)

        self.arn_slices = []
        all_arns = []
        for integration in self.integrations:
            if "function" in integration:
                self.arn_slices.append(
                    {
                        "type": "integration",
                        "path": integration["path"],
                        "method": integration["method"].lower(),
                        "length": 2,
                    }
                )
                all_arns.append(integration["function"].function_name)
                all_arns.append(integration["function"].invoke_arn)
                log.info(f"Adding integration ARN slices, path: {integration['path']}")

        for validator in self.token_validators:
            log.info(f"Processing token validator: {validator}")
            if "function" in validator:
                self.arn_slices.append(
                    {
                        "type": "token-validator",
                        "name": validator["name"],
                        "length": 2,
                    }
                )
                all_arns.append(validator["function"].function_name)
                all_arns.append(validator["function"].invoke_arn)
                log.info(
                    f"Adding token validator ARN slices, name: {validator['name']}, length: {len(all_arns)}"
                )
            elif "user_pools" in validator:
                self.arn_slices.append(
                    {
                        "type": "pool-validator",
                        "name": validator["name"],
                        "length": len(validator["user_pools"]),
                    }
                )
                for user_pool in validator["user_pools"]:
                    all_arns.append(user_pool)

        gateway_role = self._get_gateway_role()
        log.info(f"gateway_role: {gateway_role}")
        if gateway_role:
            self.arn_slices.append(
                {
                    "type": "gateway-role",
                    "length": 1,
                }
            )
            all_arns.append(gateway_role.arn)
            all_arns.append(gateway_role.name)

        log.info(f"ARN slices: {self.arn_slices}")
        log.info(f"All ARNs: {len(all_arns)}")

        # If content is provided, add it to the ARN slices.
        # Wait for all ARNs and function names to resolve, then build the API.
        def build_api(invoke_arns):
            self._build(invoke_arns)
            return self.rest_api.id

        self.rest_api_id = pulumi.Output.all(*all_arns).apply(
            lambda resolved_arns: build_api(resolved_arns)
        )

    def _build(self, invoke_arns: list[str]) -> pulumi.Output[None]:
        log.info("Building REST API with AWSOpenAPISpecEditor")

        log.info(f"Invoke ARNs: {len(invoke_arns)}")
        for i in range(len(invoke_arns)):
            log.info(f"Invoke ARN: {i} {invoke_arns[i]}")
        index = 0
        names = []
        for arn_slice in self.arn_slices:
            log.info(f"Processing ARN slice: {arn_slice}")
            if arn_slice["type"] == "integration":
                log.info(f"Adding integration: {arn_slice['path']}, index: {index}")
                names.append(invoke_arns[index])
                self.editor.add_integration(
                    path=arn_slice["path"],
                    method=arn_slice["method"],
                    function_name=invoke_arns[index],
                    invoke_arn=invoke_arns[index + 1],
                )
            elif arn_slice["type"] == "token-validator":
                log.info(f"Adding token validator: {arn_slice['name']}, index: {index}")
                names.append(invoke_arns[index])
                self.editor.add_token_validator(
                    name=arn_slice["name"],
                    function_name=invoke_arns[index],
                    invoke_arn=invoke_arns[index + 1],
                )
            elif arn_slice["type"] == "pool-validator":
                self.editor.add_user_pool_validator(
                    name=arn_slice["name"],
                    user_pool_arns=invoke_arns[index : index + arn_slice["length"]],
                )
            elif arn_slice["type"] == "gateway-role":
                self.editor.process_gateway_role(
                    self.content,
                    invoke_arns[index],
                    invoke_arns[index + 1],
                )
            else:
                raise ValueError(f"Unknown ARN slice type: {arn_slice['type']}")
            index += arn_slice["length"]

        log.info(f"Names of functions: {names}")
        # Process any S3 content integration using the last ARN (if gateway_role was provided).
        if self.content:
            self.editor.process_content(self.content, invoke_arns[-1])

        if self.path_prefix:
            log.info(f"Adding path prefix: {self.path_prefix} to all paths")
            self.editor.prefix_paths(self.path_prefix)
        self.editor.remove_unintegrated_operations()

        # Write the updated OpenAPI spec to a file for logging or debugging.
        write_logging_file(f"{self.name}.yaml", self.editor.yaml)

        # Create the RestApi resource in AWS API Gateway.
        self.rest_api = aws.apigateway.RestApi(
            self.name,
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-rest-api",
            body=self.editor.yaml,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add permissions so that API Gateway can invoke the Lambda functions.
        self._create_lambda_permissions(names)

        # Create the API Gateway deployment.
        log.info("Creating API Gateway deployment")
        deployment = aws.apigateway.Deployment(
            f"{self.name}-deployment",
            rest_api=self.rest_api.id,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.rest_api]),
        )

        # Create the API Gateway stage.
        log.info("Creating API Gateway stage")
        if self.logging:
            log.info("Setting up logging for API stage")
            log_group = aws.cloudwatch.LogGroup(
                f"{self.name}-log",
                name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-log",
                retention_in_days=7,
                opts=pulumi.ResourceOptions(parent=self),
            )
            stage = aws.apigateway.Stage(
                f"{self.name}-stage",
                rest_api=self.rest_api.id,
                deployment=deployment.id,
                stage_name=self.name,
                access_log_settings={
                    "destinationArn": log_group.arn,
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
                            "origin": "$context.request.header.Origin",
                            "authorization": "$context.request.header.Authorization",
                            "protocol": "$context.protocol",
                            "responseLength": "$context.responseLength",
                        }
                    ),
                },
                opts=pulumi.ResourceOptions(
                    parent=self,
                    depends_on=[deployment],
                ),
            )
        else:
            stage = aws.apigateway.Stage(
                f"{self.name}-stage",
                rest_api=self.rest_api.id,
                description="Stage for API Gateway",
                deployment=deployment.id,
                stage_name=self.name,
                opts=pulumi.ResourceOptions(
                    parent=self, depends_on=[deployment, self.rest_api]
                ),
            )

        # Optionally set up a firewall.
        if self.firewall:
            log.info("Setting up firewall for API")
            waf = GatewayRestApiWAF(f"{self.name}-waf", self.firewall)
            # Uncomment the following lines to attach the WAF if desired:
            # aws.wafv2.WebAclAssociation(
            #     f"{self.name}-waf-association",
            #     resource_arn=stage.arn,
            #     web_acl_arn=waf.arn,
            #     opts=pulumi.ResourceOptions(parent=self),
            # )

        self.register_outputs({"rest_api_id": self.rest_api.id})
        log.info("REST API build completed")
        return pulumi.Output.from_input(None)

    def _create_lambda_permissions(self, names: list[str]):
        """
        Create Lambda permissions for each function so that API Gateway can invoke them.
        """
        permission_names = []
        for name in names:
            if name in permission_names:
                continue
            log.info(f"Creating permission for function: {name}")
            aws.lambda_.Permission(
                f"{name}-lambda-permission",
                action="lambda:InvokeFunction",
                function=name,
                principal="apigateway.amazonaws.com",
                source_arn=self.rest_api.execution_arn.apply(lambda arn: f"{arn}/*/*"),
                opts=pulumi.ResourceOptions(parent=self),
            )
            permission_names.append(name)

    def _get_gateway_role(self):
        """
        Create and return an IAM role that allows API Gateway to access S3 content
        if content integrations are specified.
        """
        if not self.content:
            return None

        def generate_s3_policy(buckets):
            log.info(f"Buckets for S3 policy: {buckets}")
            resources = []
            for bucket in buckets:
                resources.append(f"arn:aws:s3:::{bucket}")
                resources.append(f"arn:aws:s3:::{bucket}/*")
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
        log.info(f"Bucket names: {bucket_names}")

        # Create a policy to allow API Gateway access to the given S3 buckets.
        s3_policy = aws.iam.Policy(
            f"{self.name}-s3-access-policy",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-s3-access-policy",
            description=f"Policy allowing API Gateway to access S3 buckets for {self.name}",
            policy=pulumi.Output.all(*bucket_names).apply(
                lambda buckets: generate_s3_policy(buckets)
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create an IAM role for API Gateway.
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
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Attach the S3 access policy to the role.
        aws.iam.RolePolicyAttachment(
            f"{self.name}-s3-access-attachment",
            policy_arn=s3_policy.arn,
            role=api_gateway_role.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        log.info(f"S3 access policy attached successfully: {api_gateway_role}")
        return api_gateway_role

    def get_endpoint(self):
        host = (
            "execute-api.localhost.localstack.cloud:4566"
            if is_localstack_deployment()
            else "execute-api.us-east-1.amazonaws.com"
        )
        return self.rest_api_id.apply(lambda api_id: f"{api_id}.{host}/{self.name}")


def rest_api(
    name: str,
    body: Union[str, list[str]] = None,
    integrations: list[dict] = None,
    cors_origins: str = False,
    token_validators: list[dict] = None,
    content: list[dict] = None,
    firewall: RestAPIFirewall = None,
    logging: Optional[bool] = False,
    path_prefix: Optional[str] = None,
):
    """
    Helper function to create and configure a REST API using the RestAPI component.

    Args:
        name (str): The name of the REST API.
        body (str or list[str]): The OpenAPI specification (as file path or content).
        integrations (list[dict], optional): List of Lambda integrations.
        token_validators (list[dict], optional): List of token validators.
        cors_origins (str, optional): CORS setting.
        content (list[dict], optional): S3 content integrations.
        firewall (RestAPIFirewall, optional): Firewall configuration.
        logging (bool, optional): Enable API stage logging.
        path_prefix (str, optional): A prefix to prepend to all API paths.

    Returns:
        RestAPI: The created REST API component resource.
    """
    log.info(f"Creating REST API with name: {name}")
    rest_api_instance = RestAPI(
        name=name,
        body=body,
        integrations=integrations,
        cors_origins=cors_origins,
        token_validators=token_validators,
        content=content,
        firewall=firewall,
        logging=logging,
        path_prefix=path_prefix,
    )
    log.info("REST API built successfully")

    # Export REST API ID and host.
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    pulumi.export(f"{name}-host", rest_api_instance.get_endpoint())

    return rest_api_instance
