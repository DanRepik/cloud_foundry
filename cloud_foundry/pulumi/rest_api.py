# rest_api.py

import json
import pulumi
import pulumi_aws as aws
from typing import Optional, Union
from cloud_foundry.utils.logger import logger, write_logging_file
from cloud_foundry.utils.localstack import is_localstack_deployment
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor
from .api_waf import RestAPIFirewall, GatewayRestApiWAF
from cloud_foundry.pulumi.custom_domain import CustomGatewayDomain
from cloud_foundry.utils.names import resource_id

log = logger(__name__)


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
        firewall: Optional[RestAPIFirewall] = None,
        logging: Optional[bool] = False,
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
            firewall (Optional[RestAPIFirewall], optional): Addd WAF rules to the API.
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
        self.logging = logging
        self.path_prefix = path_prefix
        self.export_api = export_api

        write_logging_file(f"{self.name}-pre.yaml", self.editor.yaml)

        log.info(f"cors_origins: {cors_origins}")
        if cors_origins:
            self.editor.cors_origins(cors_origins)

        all_arns, self.arn_alloc = self._collect_arns()

        # If content is provided, add it to the ARN slices.
        # Wait for all ARNs and function names to resolve, then build the API.
        def build(invoke_arns):
            self.invoke_arns = invoke_arns
            self._build_spec(invoke_arns)
            return self._build_api()

        self.rest_api_id = pulumi.Output.all(*all_arns).apply(
            lambda resolved_arns: build(resolved_arns)
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
                log.info(f"Adding integration ARN allocs, path: {integration['path']}")

        for validator in self.token_validators:
            log.info(f"Processing token validator: {validator}")
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
                    f"Adding token validator ARN slices, name: {validator['name']}, "
                    + f"length: {len(all_arns)}"
                )
            elif "user_pools" in validator:
                log.info(
                    f"Adding user pool validator ARN slices, name: {validator['name']}"
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
        log.info(f"gateway_role: {gateway_role}")
        if gateway_role:
            arn_alloc.append(
                {
                    "type": "gateway-role",
                    "length": 1,
                }
            )
            all_arns.append(gateway_role.arn)
            all_arns.append(gateway_role.name)

        log.info(f"ARN slices: {arn_alloc}")
        log.info(f"All ARNs: {len(all_arns)}")
        return all_arns, arn_alloc

    def _build_spec(self, invoke_arns: list[str]) -> str:
        log.info("Building API spec with AWSOpenAPISpecEditor")

        log.info(f"Invoke ARNs: {len(self.invoke_arns)}")
        for arn_slice in self.arn_alloc:
            log.info(f"Processing ARN slice: {arn_slice}")
            if arn_slice["type"] == "integration":
                log.info(
                    f"Adding integration: {arn_slice['path']}, index: {arn_slice['offset']}"
                )
                self.editor.add_integration(
                    path=arn_slice["path"],
                    method=arn_slice["method"],
                    function_name=invoke_arns[arn_slice["offset"]],
                    invoke_arn=invoke_arns[arn_slice["offset"] + 1],
                )
            elif arn_slice["type"] == "token-validator":
                log.info(
                    f"Adding validator: {arn_slice['name']}, index: {arn_slice['offset']}"
                )
                self.editor.add_token_validator(
                    name=arn_slice["name"],
                    function_name=invoke_arns[arn_slice["offset"]],
                    invoke_arn=invoke_arns[arn_slice["offset"] + 1],
                )
            elif arn_slice["type"] == "pool-validator":
                log.info(f"Adding user pool validator: {arn_slice['name']}")
                pool_arns = invoke_arns[
                    arn_slice["offset"] : arn_slice["offset"] + arn_slice["length"]
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

        # Process any S3 content integration using the last ARN
        # (if gateway_role was provided).
        if self.content:
            self.editor.process_content(self.content, invoke_arns[-1])

        if self.path_prefix:
            log.info(f"Adding path prefix: {self.path_prefix} to all paths")
            self.editor.prefix_paths(self.path_prefix)
        self.editor.remove_unintegrated_operations()

        if self.export_api:
            log.info(f"Exporting API specification for {self.name}")
            if self.export_api.startswith("s3://"):
                # Write the API specification to an S3 bucket
                bucket_name, key = self.export_api[5:].split("/", 1)
                aws.s3.BucketObject(
                    key,
                    bucket=bucket_name,
                    content=self.editor.yaml,
                    opts=pulumi.ResourceOptions(parent=self),
                )
                log.info(f"API specification exported to S3: {self.export_api}")
            else:
                # Write the API specification to a local file
                with open(self.export_api, "w") as file:
                    file.write(self.editor.yaml)
                log.info(f"API specification exported to file: {self.export_api}")

        # Write the updated OpenAPI spec to a file for logging or debugging.
        write_logging_file(f"{self.name}.yaml", self.editor.yaml)
        return self.editor.yaml

    def _build_api(self) -> pulumi.Output[None]:

        # Create the RestApi resource in AWS API Gateway.
        self.rest_api = aws.apigateway.RestApi(
            self.name,
            name=resource_id(f"{self.name}-rest-api"),
            body=self.editor.yaml,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add permissions so that API Gateway can invoke the Lambda functions.
        self._create_lambda_permissions()
        self._create_cognito_permissions()
        stage = self._create_stage()

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

        if self.hosted_zone_id:
            subdomain = (
                self.subdomain
                if self.subdomain
                else f"{pulumi.get_project()}-{pulumi.get_stack()}"
            )
            log.info(f"Setting up custom domain for API: {subdomain}")
            custom_domain = CustomGatewayDomain(
                self.name,
                subdomain=subdomain,
                rest_api_id=self.rest_api.id,
                stage_name=self.name,
                hosted_zone_id=self.hosted_zone_id,
                opts=pulumi.ResourceOptions(parent=self, depends_on=[stage]),
            )
            pulumi.export(f"{self.name}-custom-domain", custom_domain.domain_name)

        self.register_outputs({"rest_api_id": self.rest_api.id})
        log.info("REST API build completed")
        return self.rest_api.id

    def _create_stage(self):
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
            return aws.apigateway.Stage(
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
        return aws.apigateway.Stage(
            f"{self.name}-stage",
            rest_api=self.rest_api.id,
            description="Stage for API Gateway",
            deployment=deployment.id,
            stage_name=self.name,
            opts=pulumi.ResourceOptions(
                parent=self, depends_on=[deployment, self.rest_api]
            ),
        )

    def _create_lambda_permissions(self):
        """
        Create Lambda permissions for each function so that API Gateway can invoke them.
        """
        log.info("Creating Lambda permissions for API Gateway")

        function_names = self.editor.collect_function_names()
        log.info(f"Names of functions: {function_names}")

        permission_names = []
        for name in function_names:
            if name in permission_names:
                continue
            log.info(f"Creating permission for function: {name}")
            aws.lambda_.Permission(
                f"{name}",
                action="lambda:InvokeFunction",
                function=name,
                principal="apigateway.amazonaws.com",
                source_arn=self.rest_api.execution_arn.apply(lambda arn: f"{arn}/*/*"),
                opts=pulumi.ResourceOptions(parent=self),
            )
            permission_names.append(name)

    def _create_cognito_permissions(self):
        """
        Create permissions for API Gateway to access Cognito user pools.
        """
        log.info("Creating Cognito permissions for API Gateway")
        user_pool_arns = [
            self.invoke_arns[
                arn_slice["offset"] : arn_slice["offset"] + arn_slice["length"]
            ]
            for arn_slice in self.arn_alloc
            if arn_slice["type"] == "pool-validator"
        ]
        user_pool_arns = [arn for sublist in user_pool_arns for arn in sublist]

        if not user_pool_arns:
            return

        # Define the policy document
        cognito_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["apigateway:POST"],
                    "Resource": "arn:aws:apigateway:*::/restapis/*/authorizers",
                    "Condition": {
                        "ArnLike": {
                            "apigateway:CognitoUserPoolProviderArn": user_pool_arns
                        }
                    },
                },
                {
                    "Effect": "Allow",
                    "Action": ["apigateway:PATCH"],
                    "Resource": "arn:aws:apigateway:*::/restapis/*/authorizers/*",
                    "Condition": {
                        "ArnLike": {
                            "apigateway:CognitoUserPoolProviderArn": user_pool_arns
                        }
                    },
                },
            ],
        }

        # Create the IAM policy
        cognito_policy_document = json.dumps(cognito_policy)
        log.info(f"Creating Cognito permissions policy: {cognito_policy_document}")

        cognito_policy_resource = aws.iam.Policy(
            f"{self.name}-cognito-policy",
            name=f"{self.name}-cognito-policy",
            description="Policy for API Gateway to access Cognito user pools",
            policy=cognito_policy_document,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Attach the policy to the API Gateway role
        gateway_role = self._get_gateway_role()
        if gateway_role:
            aws.iam.RolePolicyAttachment(
                f"{self.name}-cognito-policy-attachment",
                policy_arn=cognito_policy_resource.arn,
                role=gateway_role.name,
                opts=pulumi.ResourceOptions(parent=self),
            )
            log.info(
                f"Attached Cognito policy to API Gateway role: {gateway_role.name}"
            )

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
    specification: Union[str, list[str]] = None,
    integrations: list[dict] = None,
    cors_origins: str = False,
    token_validators: list[dict] = None,
    content: list[dict] = None,
    hosted_zone_id: str = None,
    subdomain: str = None,
    firewall: RestAPIFirewall = None,
    logging: Optional[bool] = False,
    path_prefix: Optional[str] = None,
    export_api: Optional[str] = None,
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
        firewall (RestAPIFirewall, optional): Firewall configuration.
        logging (bool, optional): Enable API stage logging.
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
        logging=logging,
        path_prefix=path_prefix,
        export_api=export_api,
        opts=None,
    )
    log.info("REST API built successfully")

    # Export REST API ID and host.
    pulumi.export(f"{name}-id", rest_api_instance.rest_api_id)
    pulumi.export(f"{name}-host", rest_api_instance.get_endpoint())

    return rest_api_instance
