import pulumi
import pulumi_aws as aws
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class Function(pulumi.ComponentResource):

    def __init__(
        self,
        name,
        *,
        hash: str,
        archive_location: str,
        runtime: str = None,
        handler: str = None,
        timeout: int = None,
        memory_size: int = None,
        environment: dict[str, str] = None,
        actions: list[str] = None,
        opts=None,
    ):
        super().__init__("cloud_forge:lambda:Function", name, {}, opts)
        self.name = name
        self.hash = hash
        self.archive_location = archive_location
        self.runtime = runtime
        self.handler = handler
        self.environment = environment or {}
        self.memory_size = memory_size
        self.timeout = timeout
        self.actions = actions
        self.function_name = f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}"
        self.lambda_: pulumi.aws.Function = None

    @property
    def invoke_arn(self) -> pulumi.Output[str]:
        if not self.lambda_:
            self._create_lambda_function()
        return self.lambda_.invoke_arn

    def _create_lambda_function(self) -> aws.lambda_.Function:
        log.debug("creating lambda function")

        execution_role = self.create_execution_role()

        self.lambda_ = aws.lambda_.Function(
            f"{self.name}-lambda",
            code=pulumi.FileArchive(self.archive_location),
            name=self.function_name,
            role=execution_role.arn,
            memory_size=self.memory_size,
            timeout=self.timeout,
            handler=self.handler or "app.handler",
            source_code_hash=self.hash,
            runtime=self.runtime or aws.lambda_.Runtime.PYTHON3D9,
            environment=aws.lambda_.FunctionEnvironmentArgs(variables=self.environment),
            opts=pulumi.ResourceOptions(depends_on=[execution_role], parent=self),
        )
        pulumi.export(f"{self.name}-invoke-arn", self.lambda_.invoke_arn)
        pulumi.export(f"{self.name}-name", self.function_name)
        self.register_outputs(
            {
                "invoke-arn": self.lambda_.invoke_arn,
                "function_name": self.function_name,
            }
        )

    def create_execution_role(self) -> aws.iam.Role:
        log.debug("creating execution role")
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

        log.info(f"assume_role_policy: {assume_role_policy}")
        role = aws.iam.Role(
            f"{self.name}-lambda-execution",
            assume_role_policy=assume_role_policy.json,
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}-lambda-execution",
            opts=pulumi.ResourceOptions(parent=self),
        )

        policy_document = aws.iam.get_policy_document(
            statements=[
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    actions=(
                        (self.actions or [])
                        + [
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                        ]
                    ),
                    resources=["*"],
                )
            ]
        )

        log.info(f"policy_document: {policy_document.json}")
        aws.iam.RolePolicy(
            f"{self.name}-lambda-policy",
            role=role.id,
            policy=policy_document.json,
            opts=pulumi.ResourceOptions(depends_on=[role], parent=self)
        )

        return role
