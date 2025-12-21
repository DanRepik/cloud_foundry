# rest_api.py

import json
import logging
import os
from typing import Optional, Union

import pulumi
import pulumi_aws as aws

from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor
from cloud_foundry.pulumi.custom_domain import CustomGatewayDomain
from cloud_foundry.utils.names import resource_id

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class RestAPI(pulumi.ComponentResource):
    """
    A Pulumi component resource that creates and manages an AWS API Gateway REST API
    with Lambda integrations and token validators.

    This class uses AWSOpenAPISpecEditor to process the OpenAPI spec by attaching
    Lambda integrations, Cognito or Lambda token validators, and S3 content
    integrations.
    """

    rest_api: Optional[aws.apigateway.RestApi] = None
    rest_api_id: pulumi.Output[str] = None  # The REST API identifier
    domain: Optional[str] = None  # The custom domain name for the API

    def __init__(
        self,
        name: str,
        specification: Optional[Union[str, list[str]]] = None,
        integrations: Optional[list[dict]] = None,
        hosted_zone_id: Optional[str] = None,
        subdomain: Optional[str] = None,
        cors_origins: Optional[str] = False,
        content: Optional[list[dict]] = None,
        token_validators: Optional[list[dict]] = None,
        firewall: Optional[dict] = None,
        enable_logging: Optional[bool] = False,
        path_prefix: Optional[str] = None,
        export_api: Optional[str] = None,
        opts=None,
    ):
        """
        Initialize the RestAPI component resource.

        Args:
            name (str): The name of the REST API.
            specification (Optional[Union[str, list[str]]]): The OpenAPI
            specification for the API.
            integrations (Optional[list[dict]], optional): List of integrations
            defining Lambda functions for path operations.
            token_validators (Optional[list[dict]], optional): List of token
            validators for authentication.
            cors_origins (Optional[str], optional): If truthy, enables CORS in
            the API spec.
            content (Optional[list[dict]], optional): List of static content
            definitions (e.g. S3 integrations).
            firewall (Optional[dict], optional): Addd WAF rules to the API.
            logging (Optional[bool], optional): Enable API Gateway stage logging.
            path_prefix (Optional[str], optional): A prefix to prepend to
            all API paths.
            export_api (Optional[str], optional): Name to export the API details.
            opts (pulumi.ResourceOptions, optional): Additional resource options.
        """
        super().__init__("cloud_foundry:apigw:RestAPI", name, None, opts)
        self.name = name
        self.integrations = integrations or []
        self.token_validators = token_validators or []
        self.hosted_zone_id = hosted_zone_id
        self.subdomain = subdomain
        self.specification = specification
        self.content = content or []
        self.editor = AWSOpenAPISpecEditor(specification)
        self.firewall = firewall
        self.enable_logging = enable_logging
        self.path_prefix = path_prefix
        self.export_api = export_api

        # Validate token validators before proceeding
        self._validate_token_validators()

        # Collect ARNs for integrations and token validators
        all_arns, self.arn_alloc = self._collect_arns()

        # Build the API spec and create the RestApi resource
        self.rest_api = pulumi.Output.all(*all_arns).apply(
            lambda resolved_arns: self._create_rest_api(resolved_arns)
        )
        self.rest_api_id = self.rest_api.id

        # Create the API Gateway stage
        self.stage = self.rest_api.apply(lambda rest_api: self._create_stage(rest_api))

        # Optionally set up a custom domain
        if self.hosted_zone_id:
            self.domain = self.stage.apply(
                lambda stage: self.create_custom_domain(
                    self.hosted_zone_id, self.subdomain
                )
            )
        else:
            # Set domain to the default execute-api endpoint
            self.domain = pulumi.Output.concat(
                self.rest_api.id,
                ".execute-api.",
                os.getenv("AWS_REGION") or aws.get_region().name,
                ".amazonaws.com/",
                self.stage.stage_name,
            )

        log.info("registering outputs for %s API", self.name)
        # Register outputs
        self.rest_api_id = self.rest_api.id
        self.stage_name = self.stage.stage_name
        self.register_outputs(
            {
                "rest-api-id": self.rest_api_id,
                "stage-name": self.stage_name,
                "domain": self.domain,
            }
        )

    def _validate_token_validators(self):
        """
        Validate the token_validators attribute to ensure:
        - Each validator has a unique name.
        - Either 'user_pools' or 'function' is defined, but not both.
        """
        if not self.token_validators:
            return

        seen_names = set()
        for validator in self.token_validators:
            name = validator.get("name")
            if not name:
                raise ValueError("Each token validator must have a 'name' attribute.")
            if name in seen_names:
                raise ValueError(f"Duplicate token validator name found: {name}")
            seen_names.add(name)

            has_user_pools = "user_pools" in validator
            has_function = "function" in validator
            if has_user_pools and has_function:
                raise ValueError(
                    f"Token validator '{name}' "
                    + "cannot have both 'user_pools' and 'function' defined."
                )
            if not has_user_pools and not has_function:
                raise ValueError(
                    f"Token validator '{name}' "
                    + "must have either 'user_pools' or 'function' defined."
                )

    def _collect_arns(self):
        arn_alloc = []
        all_arns = []
        for integration in self.integrations:
            if "function" in integration:
                if isinstance(integration["function"], str):
                    integration["function"] = aws.lambda_.Function.get(
                        integration["function"], integration["function"]
                    )
                arn_alloc.append(
                    {
                        "type": "integration",
                        "path": integration["path"],
                        "method": integration["method"].lower(),
                        "length": 2,
                        "offset": len(all_arns),
                    }
                )
                all_arns.append(integration["function"].function_name)
                all_arns.append(integration["function"].invoke_arn)
                log.info(
                    "Adding integration ARN allocs, path: %s",
                    integration["path"],
                )

        for validator in self.token_validators:
            log.info("Processing token validator: %s", validator)
            if "function" in validator:
                if isinstance(validator["function"], str):
                    validator["function"] = aws.lambda_.Function.get(
                        validator["function"], validator["function"]
                    )
                arn_alloc.append(
                    {
                        "type": "token-validator",
                        "name": validator["name"],
                        "length": 2,
                        "offset": len(all_arns),
                    }
                )
                all_arns.append(validator["function"].function_name)
                all_arns.append(validator["function"].invoke_arn)
                log.info(
                    "Adding token validator ARN slices, name: %s, length: %d",
                    validator["name"],
                    len(all_arns),
                )
            elif "user_pools" in validator:
                log.info(
                    "Adding user pool validator ARN slices, name: %s",
                    validator["name"],
                )
                arn_alloc.append(
                    {
                        "type": "pool-validator",
                        "name": validator["name"],
                        "length": len(validator["user_pools"]),
                        "offset": len(all_arns),
                    }
                )
                for user_pool in validator["user_pools"]:
                    all_arns.append(user_pool)

        gateway_role = self._get_gateway_role()
        log.info("gateway_role: %s", gateway_role)
        if gateway_role:
            arn_alloc.append(
                {
                    "type": "gateway-role",
                    "length": 1,
                }
            )
            all_arns.append(gateway_role.arn)
            all_arns.append(gateway_role.name)
        return all_arns, arn_alloc

    def _build_spec(self, invoke_arns: list[str]) -> str:
        log.info("Building API spec with AWSOpenAPISpecEditor")

        # Apply path prefix first if specified
        if self.path_prefix:
            log.info("Adding path prefix: %s to all paths", self.path_prefix)
            self.editor.prefix_paths(self.path_prefix)

        for arn_slice in self.arn_alloc:
            if arn_slice["type"] == "integration":
                # Apply prefix to integration path to match the prefixed spec paths
                integration_path = arn_slice["path"]
                if self.path_prefix:
                    integration_path = (
                        f"{self.path_prefix.rstrip('/')}/{integration_path.lstrip('/')}"
                    )

                self.editor.add_integration(
                    path=integration_path,
                    method=arn_slice["method"],
                    function_name=invoke_arns[arn_slice["offset"]],
                    invoke_arn=invoke_arns[arn_slice["offset"] + 1],
                )
            elif arn_slice["type"] == "token-validator":
                self.editor.add_token_validator(
                    name=arn_slice["name"],
                    function_name=invoke_arns[arn_slice["offset"]],
                    invoke_arn=invoke_arns[arn_slice["offset"] + 1],
                )
            elif arn_slice["type"] == "pool-validator":
                pool_arns = invoke_arns[
                    arn_slice["offset"] : (arn_slice["offset"] + arn_slice["length"])
                ]
                self.editor.add_user_pool_validator(
                    name=arn_slice["name"],
                    user_pool_arns=pool_arns,
                )
            elif arn_slice["type"] == "gateway-role":
                self.editor.process_gateway_role(
                    self.content,
                    invoke_arns[arn_slice["offset"]],
                    invoke_arns[arn_slice["offset"] + 1],
                )
            else:
                raise ValueError(f"Unknown ARN slice type: {arn_slice['type']}")

        self.api_spec = self.editor.yaml

    def _create_rest_api(self, invoke_arns: list[str]) -> aws.apigateway.RestApi:
        """
        Create the RestApi resource in AWS API Gateway.
        """
        log.info("Building API spec with AWSOpenAPISpecEditor")
        self._build_spec(invoke_arns)
        self._create_lambda_permissions()
        self._create_cognito_permissions(invoke_arns)

        log.info("Exporting API specification for %s", self.name)
        if self.export_api:
            log.info("Exporting API specification for %s", self.name)
            if self.export_api.startswith("s3://"):
                # Write the API specification to an S3 bucket
                bucket_name, key = self.export_api[5:].split("/", 1)
                aws.s3.BucketObject(
                    key,
                    bucket=bucket_name,
                    opts=pulumi.ResourceOptions(parent=self),
                )
                log.info("API specification exported to S3: %s", self.export_api)
            else:
                log.info("API specification exported to file: %s", self.export_api)
                with open(self.export_api, "w") as file:
                    file.write(self.editor.yaml)
                log.info("API specification exported to file: %s", self.export_api)

        log.info("Creating RestApi resource")
        return aws.apigateway.RestApi(
            self.name,
            name=resource_id(f"{self.name}-rest-api"),
            body=self.api_spec,
            opts=pulumi.ResourceOptions(parent=self),
        )

    def _create_stage(self, rest_api: aws.apigateway.RestApi) -> aws.apigateway.Stage:
        """
        Create the API Gateway stage.
        """
        log.info("Creating API Gateway deployment")
        deployment = aws.apigateway.Deployment(
            f"{self.name}-deployment",
            rest_api=rest_api.id,
            triggers={
                "redeployment": pulumi.Output.json_dumps(self.api_spec),
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[rest_api]),
        )

        log.info("Creating API Gateway stage")
        if self.enable_logging:
            log.info("Setting up logging for API stage")
            log_group = aws.cloudwatch.LogGroup(
                f"{self.name}-log",
                name=f"/aws/api/{pulumi.get_project()}/{pulumi.get_stack()}/{self.name}",  # noqa
                retention_in_days=3,
                opts=pulumi.ResourceOptions(parent=self, retain_on_delete=False),
            )
            return aws.apigateway.Stage(
                f"{self.name}-stage",
                rest_api=rest_api.id,
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
        return aws.apigateway.Stage(
            f"{self.name}-stage",
            rest_api=rest_api.id,
            deployment=deployment.id,
            stage_name=self.name,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[deployment, rest_api]),
        )

    def create_custom_domain(self, hosted_zone_id: str, subdomain: str) -> str:

        if not hosted_zone_id:
            raise ValueError("Hosted zone ID is required for custom domain.")

        subdomain = subdomain if subdomain else resource_id(self.name)

        custom_domain = CustomGatewayDomain(
            name=self.name,
            hosted_zone_id=hosted_zone_id,
            subdomain=subdomain,
            rest_api_id=self.rest_api.id,
            stage_name=self.stage.apply(lambda s: s.stage_name),
            opts=pulumi.ResourceOptions(
                parent=self, depends_on=[self.rest_api, self.stage]
            ),
        )

        return custom_domain.domain_name

    def _create_lambda_permissions(self):
        """
        Create Lambda permissions for each function so that API Gateway can invoke them.
        """
        function_names = self.editor.collect_function_names()
        log.info("Names of functions: %s", function_names)

        permission_names = []
        for name in function_names:
            log.info("Creating permission for function: %s", name)
            # Create unique permission name by combining REST API name
            # with function name
            permission_name = f"{self.name}-{name}-permission"
            if permission_name not in permission_names:
                aws.lambda_.Permission(
                    permission_name,
                    action="lambda:InvokeFunction",
                    function=name,
                    principal="apigateway.amazonaws.com",
                    source_arn=self.rest_api.execution_arn.apply(
                        lambda arn: f"{arn}/*/*"
                    ),
                    opts=pulumi.ResourceOptions(parent=self),
                )
                permission_names.append(permission_name)

    def _create_cognito_permissions(self, invoke_arns: list[str]):
        """
        Create permissions for API Gateway to access Cognito user pools.
        Handles both plain strings and Pulumi Output objects in invoke_arns.
        """
        log.info("Creating Cognito permissions for API Gateway")
        user_pool_arns = [
            invoke_arns[
                arn_slice["offset"] : (arn_slice["offset"] + arn_slice["length"])
            ]
            for arn_slice in self.arn_alloc
            if arn_slice["type"] == "pool-validator"
        ]
        # Flatten the list
        user_pool_arns = [arn for sublist in user_pool_arns for arn in sublist]

        if not user_pool_arns:
            return

        def create_policy(user_pool_arns_resolved):
            # Remove None and empty values
            arns = [arn for arn in user_pool_arns_resolved if arn]
            if not arns:
                return

            cognito_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["apigateway:POST"],
                        "Resource": "arn:aws:apigateway:*::/restapis/*/authorizers",
                        "Condition": {
                            "ArnLike": {"apigateway:CognitoUserPoolProviderArn": arns}
                        },
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["apigateway:PATCH"],
                        "Resource": "arn:aws:apigateway:*::/restapis/*/authorizers/*",
                        "Condition": {
                            "ArnLike": {"apigateway:CognitoUserPoolProviderArn": arns}
                        },
                    },
                ],
            }
            cognito_policy_document = json.dumps(cognito_policy)
            log.info("Creating Cognito permissions policy: %s", cognito_policy_document)

            cognito_policy_resource = aws.iam.Policy(
                f"{self.name}-cognito-policy",
                name=f"{self.name}-cognito-policy",
                description="Policy for API Gateway to access Cognito user pools",
                policy=cognito_policy_document,
                opts=pulumi.ResourceOptions(parent=self),
            )

            gateway_role = self._get_gateway_role()
            if gateway_role:
                aws.iam.RolePolicyAttachment(
                    f"{self.name}-cognito-policy-attachment",
                    policy_arn=cognito_policy_resource.arn,
                    role=gateway_role.name,
                    opts=pulumi.ResourceOptions(parent=self),
                )
                log.info(
                    "Attached Cognito policy to API Gateway role: %s",
                    gateway_role.name,
                )

        # If any item is a Pulumi Output, use Output.all to resolve them
        if any(isinstance(arn, pulumi.Output) for arn in user_pool_arns):
            pulumi.Output.all(*user_pool_arns).apply(create_policy)
        else:
            create_policy(user_pool_arns)

    def _get_gateway_role(self):
        """
        Create and return an IAM role that allows API Gateway to access S3 content
        if content integrations are specified.
        """
        if not self.content:
            return None

        def generate_s3_policy(buckets):
            log.info("Buckets for S3 policy: %s", buckets)
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
            name=f"{resource_id(self.name)}-s3-access-policy",
            description=f"Policy allowing gateway access S3 buckets for {self.name}",
            policy=pulumi.Output.all(*bucket_names).apply(
                lambda buckets: generate_s3_policy(buckets)
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create an IAM role for API Gateway.
        api_gateway_role = aws.iam.Role(
            f"{self.name}-api-gw-role",
            name=resource_id(f"{self.name}-api-gw-role"),
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
            opts=pulumi.ResourceOptions(parent=self),
        )
        log.info("S3 access policy attached successfully: %s", api_gateway_role)

        return api_gateway_role

    def get_endpoint(self):
        host = "execute-api.us-east-1.amazonaws.com"
        return self.rest_api.id.apply(lambda api_id: f"{api_id}.{host}/{self.name}")


def rest_api(
    name: str,
    specification: Union[str, list[str]] = None,
    integrations: list[dict] = None,
    cors_origins: str = False,
    token_validators: list[dict] = None,
    content: list[dict] = None,
    hosted_zone_id: str = None,
    subdomain: str = None,
    firewall: dict = None,
    enable_logging: Optional[bool] = False,
    path_prefix: Optional[str] = None,
    export_api: Optional[str] = None,
    opts: Optional[pulumi.ResourceOptions] = None,
):
    """
    Helper function to create and configure a REST API using the RestAPI component.

    Args:
        name (str): The name of the REST API.
        specification (str or list[str]): The OpenAPI specification (as file path
        or content).
        integrations (list[dict], optional): List of Lambda integrations.
        token_validators (list[dict], optional): List of token validators.
        cors_origins (str, optional): CORS setting.
        content (list[dict], optional): S3 content integrations.
        firewall (dict, optional): Firewall configuration.
        enable_logging (bool, optional): Enable API stage logging.
        path_prefix (str, optional): A prefix to prepend to all API paths.
        export_api (str, optional): Name to export the API details.

    Returns:
        RestAPI: The created REST API component resource.
    """
    log.info(f"Creating REST API with name: {name}")
    rest_api_instance = RestAPI(
        name=name,
        specification=specification,
        integrations=integrations,
        cors_origins=cors_origins,
        token_validators=token_validators,
        content=content,
        hosted_zone_id=hosted_zone_id,
        subdomain=subdomain,
        firewall=firewall,
        enable_logging=enable_logging,
        path_prefix=path_prefix,
        export_api=export_api,
        opts=opts,
    )
    log.info("REST API built successfully")

    return rest_api_instance
