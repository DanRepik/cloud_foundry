# function.py

import pulumi
import pulumi_aws as aws
from typing import Union
from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.names import resource_id

log = logger(__name__)


class Function(pulumi.ComponentResource):
    lambda_: aws.lambda_.Function

    def __init__(
        self,
        name,
        *,
        archive_location: str = None,
        hash: str = None,
        runtime: str = None,
        handler: str = None,
        timeout: int = None,
        memory_size: int = None,
        environment: dict[str, Union[str, pulumi.Output[str]]] = None,
        policy_statements: list = None,
        vpc_config: dict = None,
        use_parameter_store: bool = False,
        opts=None,
    ):
        super().__init__("cloud_foundry:lambda:Function", name, {}, opts)
        self.name = name
        self.archive_location = archive_location
        self.hash = hash
        self.runtime = runtime
        self.handler = handler
        self.environment = environment or {}
        self.memory_size = memory_size
        self.timeout = timeout
        self.policy_statements = policy_statements or []
        self.vpc_config = vpc_config or {}
        self.function_name = f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}"
        self.log_group_name = f"/aws/lambda/{self.function_name}"
        # Validate that the environment is a dictionary with string keys and values
        # Filter out None values and convert them to empty strings
        if isinstance(self.environment, dict):
            self.environment = {
                k: v if v is not None else "" for k, v in self.environment.items()
            }
        if not isinstance(self.environment, dict) or not all(
            isinstance(k, str) and (isinstance(v, str) or isinstance(v, pulumi.Output))
            for k, v in self.environment.items()
        ):
            raise ValueError(
                "The 'environment' parameter must be a dictionary with string keys and string values. "
                + f"environment: {self.environment}"
            )

        # Import existing Lambda function if no creation parameters are provided
        if not archive_location and not hash and not runtime and not handler:
            log.info(f"Importing existing Lambda function: {self.function_name}")
            self.lambda_ = aws.lambda_.Function.get(
                f"{self.name}-lambda",
                self.name,
                opts=pulumi.ResourceOptions(parent=self),
            )
        else:
            self._create_lambda_function()

    @property
    def arn(self) -> pulumi.Output[str]:
        return self.lambda_.arn

    @property
    def invoke_arn(self) -> pulumi.Output[str]:
        return self.lambda_.invoke_arn

    def _create_lambda_function(self) -> aws.lambda_.Function:
        log.info(f"Creating Lambda function: {self.function_name}")

        # Create the execution role
        execution_role = self.create_execution_role()

        # Define VPC configuration if provided
        vpc_config_args = None
        if self.vpc_config:
            vpc_config_args = aws.lambda_.FunctionVpcConfigArgs(
                subnet_ids=self.vpc_config.get("subnet_ids", []),
                security_group_ids=self.vpc_config.get("security_group_ids", []),
            )

        # Set the retention time for the function logs
        log_group = aws.cloudwatch.LogGroup(
            f"{self.name}-log-group",
            name=self.log_group_name,
            retention_in_days=3,  # Set the retention period in days
            opts=pulumi.ResourceOptions(retain_on_delete=False),
        )

        # Create the Lambda function
        # Handle environment variables - if any are Outputs, we need special handling
        log.info(f"Environment dict type: {type(self.environment)}")
        log.info(
            f"Environment keys: {list(self.environment.keys()) if self.environment else 'None'}"
        )

        # Check if any environment values are Outputs
        has_outputs = any(
            isinstance(v, pulumi.Output)
            for v in (self.environment.values() if self.environment else [])
        )

        if self.environment and has_outputs:
            # If we have Outputs, resolve them all first, then create FunctionEnvironmentArgs
            log.info(
                "Environment contains Output objects - using Output.all() to resolve"
            )
            env_dict = pulumi.Output.all(**self.environment)
            environment_args = env_dict.apply(
                lambda resolved: aws.lambda_.FunctionEnvironmentArgs(variables=resolved)
            )
        elif self.environment:
            # All values are plain strings
            log.info("Environment contains only string values")
            environment_args = aws.lambda_.FunctionEnvironmentArgs(
                variables=self.environment
            )
        else:
            environment_args = None

        log.info(f"Environment args type: {type(environment_args)}")

        self.lambda_ = aws.lambda_.Function(
            f"{self.name}-function",
            code=pulumi.FileArchive(self.archive_location),
            name=self.function_name,
            role=execution_role.arn,
            memory_size=self.memory_size,
            timeout=self.timeout,
            handler=self.handler or "app.handler",
            source_code_hash=self.hash,
            runtime=self.runtime or aws.lambda_.Runtime.PYTHON3D13,
            environment=environment_args,
            vpc_config=vpc_config_args,
            opts=pulumi.ResourceOptions(
                depends_on=[execution_role, log_group], parent=self
            ),
        )

        # Register outputs
        self.register_outputs(
            {
                "invoke_arn": self.lambda_.invoke_arn,
                "function_name": self.function_name,
                "log_group_name": self.log_group_name,
            }
        )

    def create_execution_role(self) -> aws.iam.Role:
        log.info(f"Creating execution role for Lambda function: {self.function_name}")

        # Define the assume role policy
        assume_role_policy = aws.iam.get_policy_document(
            statements=[
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    principals=[
                        aws.iam.GetPolicyDocumentStatementPrincipalArgs(
                            type="Service",
                            identifiers=["lambda.amazonaws.com"],
                        )
                    ],
                    actions=["sts:AssumeRole"],
                )
            ]
        )

        # Create the IAM role
        role = aws.iam.Role(
            f"{self.name}-role",
            assume_role_policy=assume_role_policy.json,
            name=f"{resource_id(self.name)}-lambda",
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Build policy statements
        base_policy_statements = [
            aws.iam.GetPolicyDocumentStatementArgs(
                effect="Allow",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        ]

        # Handle user-defined policy statements - they might be a Pulumi Output
        def build_policy_statements(user_statements):
            policy_statements = base_policy_statements.copy()

            # Add user-defined policy statements
            for statement in user_statements:
                if isinstance(statement, str):
                    # Parse JSON string to dict
                    import json

                    statement = json.loads(statement)

                if isinstance(statement, dict):
                    # Support both AWS standard (Action/Resource) and plural (Actions/Resources)
                    actions = statement.get("Actions") or statement.get("Action") or []
                    resources = (
                        statement.get("Resources") or statement.get("Resource") or []
                    )

                    # Normalize to list if single string
                    if isinstance(actions, str):
                        actions = [actions]
                    if isinstance(resources, str):
                        resources = [resources]

                    # Filter out None/empty values
                    actions = [a for a in actions if a]
                    resources = [r for r in resources if r]

                    # Skip statement if no actions or resources
                    if not actions or not resources:
                        log.warning(
                            f"Skipping policy statement with empty actions or resources: {statement}"
                        )
                        continue

                    log.info(f"Adding user-defined policy statement: {statement}")
                    policy_statements.append(
                        aws.iam.GetPolicyDocumentStatementArgs(
                            effect=statement.get("Effect", "Allow"),
                            actions=actions,
                            resources=resources,
                        )
                    )

            # Add VPC-related permissions if VPC config is provided
            if self.vpc_config:
                policy_statements.extend(
                    [
                        aws.iam.GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            actions=[
                                "ec2:CreateNetworkInterface",
                                "ec2:DescribeNetworkInterfaces",
                                "ec2:DeleteNetworkInterface",
                                "ec2:AssignPrivateIpAddresses",
                                "ec2:UnassignPrivateIpAddresses",
                            ],
                            resources=["*"],
                        ),
                        aws.iam.GetPolicyDocumentStatementArgs(
                            effect="Allow",
                            actions=[
                                "ec2:DescribeSubnets",
                                "ec2:DescribeSecurityGroups",
                                "ec2:DescribeVpcEndpoints",
                            ],
                            resources=["*"],
                        ),
                    ]
                )

            return policy_statements

        # Check if policy_statements is a Pulumi Output
        if isinstance(self.policy_statements, pulumi.Output):
            # Use apply to handle the Output case
            policy_statements = self.policy_statements.apply(build_policy_statements)
        else:
            # Handle the regular list case
            policy_statements = build_policy_statements(self.policy_statements or [])

        # Create the policy document - handle both Output and regular cases
        if isinstance(policy_statements, pulumi.Output):

            def create_policy_doc(statements):
                log.info(f"Creating policy document with {len(statements)} statements")
                for i, stmt in enumerate(statements):
                    log.info(
                        f"Statement {i}: effect={stmt.effect}, actions={stmt.actions}, resources={stmt.resources}"
                    )
                return aws.iam.get_policy_document(statements=statements).json

            policy_json = policy_statements.apply(create_policy_doc)
        else:
            log.info(f"policy_statements count: {len(policy_statements)}")
            for i, stmt in enumerate(policy_statements):
                log.info(
                    f"Statement {i}: effect={stmt.effect}, actions={stmt.actions}, resources={stmt.resources}"
                )
            policy_document = aws.iam.get_policy_document(statements=policy_statements)
            policy_json = policy_document.json

        # Attach the policy to the role
        aws.iam.RolePolicy(
            f"{self.name}-role-policy",
            role=role.id,
            policy=policy_json,
            opts=pulumi.ResourceOptions(depends_on=[role], parent=self),
        )

        return role


def import_function(name: str) -> Function:
    return Function(name)


def function(
    name,
    *,
    archive_location: str = None,
    hash: str = None,
    runtime: str = None,
    handler: str = None,
    timeout: int = None,
    memory_size: int = None,
    environment: dict[str, str] = None,
    policy_statements: list = None,
    vpc_config: dict = None,
    opts=None,
) -> Function:
    """
    Factory function to create a Lambda function.

    Args:
        name (str): The name of the Lambda function.
        archive_location (str): The location of the Lambda function code
            archive.
        hash (str): The source code hash for the Lambda function.
        runtime (str): The runtime for the Lambda function (e.g., Python 3.9).
        handler (str): The handler for the Lambda function.
        timeout (int): The timeout for the Lambda function in seconds.
        memory_size (int): The memory size for the Lambda function in MB.
        environment (dict[str, str]): Environment variables for
            the Lambda function.
        policy_statements (list): IAM policy statements for the
            Lambda function.
        vpc_config (dict): VPC configuration for the Lambda function.
        opts: Pulumi resource options.

    Returns:
        Function: A Pulumi-managed Lambda function.
    """
    return Function(
        name,
        archive_location=archive_location,
        hash=hash,
        runtime=runtime,
        handler=handler,
        timeout=timeout,
        memory_size=memory_size,
        environment=environment,
        policy_statements=policy_statements,
        vpc_config=vpc_config,
        opts=opts,
    )
