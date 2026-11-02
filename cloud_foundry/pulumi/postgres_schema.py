"""Own a Postgres schema on a shared Aurora cluster: login role, secret,
schemas, extensions and a bundled schema script, applied over the RDS Data
API on every change.

Creates a credentials secret for the role, a bootstrap Lambda (no VPC; see
``cloud_foundry/services/postgres_schema_bootstrap.py``) and an invocation
that re-runs it when the script, the configuration or the password changes.

Example:
    >>> from cloud_foundry import postgres_schema
    >>> insight_db = postgres_schema(
    ...     "insight-db",
    ...     cluster_arn=shared_cluster_arn,
    ...     master_secret_arn=shared_secret_arn,
    ...     database="candidate_evidence",
    ...     role_name="insight_app",
    ...     schemas=["insight"],
    ...     extensions=[{"name": "vector", "schema": "insight"}],
    ...     member_of=["cep_lens_reader"],
    ...     search_path=["insight", "cep", "public"],
    ...     schema_sql_path="infra/index/resources/insight_schema.sql",
    ... )
    >>> insight_db.secret_arn  # credentials for the role
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from pulumi import ComponentResource, Input, Output, ResourceOptions

from cloud_foundry.pulumi.python_function import python_function
from cloud_foundry.utils.names import resource_id

_SERVICE = "file://" + str(
    Path(__file__).resolve().parent.parent / "services" / "postgres_schema_bootstrap.py"
)


class PostgresSchema(ComponentResource):
    """A login role and its schema, kept in step with a script.

    Attributes:
        secret (aws.secretsmanager.Secret): The role's credentials
            (``username``, ``password``, ``engine``, ``database`` and, when
            given, ``host`` and ``port``).
        function: The bootstrap Lambda.
        invocation (aws.lambda_.Invocation): The latest bootstrap run; its
            ``result`` is the handler's JSON summary.
    """

    def __init__(
        self,
        name: str,
        *,
        cluster_arn: Input[str],
        master_secret_arn: Input[str],
        database: Input[str],
        role_name: str,
        schema_sql_path: Optional[str] = None,
        schemas: Optional[list[str]] = None,
        extensions: Optional[list[dict]] = None,
        member_of: Optional[list[str]] = None,
        search_path: Optional[list[str]] = None,
        create_database: bool = False,
        maintenance_database: str = "postgres",
        host: Optional[Input[str]] = None,
        port: Optional[Input[int]] = None,
        opts: Optional[ResourceOptions] = None,
    ):
        super().__init__("cloud_foundry:postgres:PostgresSchema", name, {}, opts)
        child = ResourceOptions(parent=self)
        rid = resource_id(name)

        password = random.RandomPassword(
            f"{name}-password", length=32, special=False, opts=child
        )
        self.secret = aws.secretsmanager.Secret(
            f"{name}-secret",
            name=f"{rid}-credentials",
            description=f"Postgres credentials for role {role_name}",
            recovery_window_in_days=0,
            opts=child,
        )
        secret_version = aws.secretsmanager.SecretVersion(
            f"{name}-secret-version",
            secret_id=self.secret.id,
            secret_string=Output.all(
                password=password.result, database=database, host=host, port=port
            ).apply(
                lambda v: json.dumps(
                    {
                        key: value
                        for key, value in {
                            "username": role_name,
                            "password": v["password"],
                            "engine": "postgres",
                            "database": v["database"],
                            "host": v["host"],
                            "port": v["port"],
                        }.items()
                        if value is not None
                    }
                )
            ),
            opts=child,
        )

        # Static structure only; ARNs and the database name may be Outputs,
        # so they travel in the environment instead.
        config = {
            "role_name": role_name,
            "schemas": schemas or [],
            "extensions": extensions or [],
            "member_of": member_of or [],
            "search_path": search_path or [],
            "create_database": create_database,
        }
        config_json = json.dumps(config, sort_keys=True)
        schema_sql = (
            Path(schema_sql_path).read_text(encoding="utf-8") if schema_sql_path else ""
        )

        sources = {
            "app.py": _SERVICE,
            "config.json": config_json,
        }
        if schema_sql_path:
            sources["schema.sql"] = "file://" + str(Path(schema_sql_path).resolve())

        self.function = python_function(
            f"{name}-bootstrap",
            sources=sources,
            # Bundled rather than the runtime's boto3, which can predate
            # rds-data's DatabaseResumingException (auto-pause).
            requirements=["boto3"],
            timeout=300,
            environment={
                "CLUSTER_ARN": cluster_arn,
                "MASTER_SECRET_ARN": master_secret_arn,
                "ROLE_SECRET_ARN": self.secret.arn,
                "DATABASE": database,
                "MAINTENANCE_DATABASE": maintenance_database,
            },
            policy_statements=[
                {
                    "Effect": "Allow",
                    "Actions": [
                        "rds-data:ExecuteStatement",
                        "rds-data:BeginTransaction",
                        "rds-data:CommitTransaction",
                        "rds-data:RollbackTransaction",
                    ],
                    "Resources": [cluster_arn],
                },
                {
                    "Effect": "Allow",
                    "Actions": ["secretsmanager:GetSecretValue"],
                    "Resources": [master_secret_arn, self.secret.arn],
                },
            ],
            opts=child,
        )

        digest = hashlib.sha256((config_json + "\n" + schema_sql).encode()).hexdigest()
        self.invocation = aws.lambda_.Invocation(
            f"{name}-invoke",
            # The Lambda resource's name Output, not Function.function_name
            # (a plain string): only the Output makes Pulumi wait for the
            # function to exist before invoking it.
            function_name=self.function.lambda_.name,
            # The handler ignores the event; input and triggers only make
            # Pulumi re-invoke when the script, configuration or password
            # changes.
            input=json.dumps({"digest": digest}),
            triggers={
                "digest": digest,
                "secret_version": secret_version.version_id,
            },
            opts=ResourceOptions(parent=self, depends_on=[secret_version]),
        )

        self.register_outputs(
            {"secret_arn": self.secret.arn, "result": self.invocation.result}
        )

    @property
    def secret_arn(self) -> Output[str]:
        return self.secret.arn

    @property
    def result(self) -> Output[str]:
        return self.invocation.result


def postgres_schema(
    name: str,
    *,
    cluster_arn: Input[str],
    master_secret_arn: Input[str],
    database: Input[str],
    role_name: str,
    schema_sql_path: Optional[str] = None,
    schemas: Optional[list[str]] = None,
    extensions: Optional[list[dict]] = None,
    member_of: Optional[list[str]] = None,
    search_path: Optional[list[str]] = None,
    create_database: bool = False,
    maintenance_database: str = "postgres",
    host: Optional[Input[str]] = None,
    port: Optional[Input[int]] = None,
    opts: Optional[ResourceOptions] = None,
) -> PostgresSchema:
    """Create a PostgresSchema component.

    Args:
        name: Logical name; the secret is ``<resource_id(name)>-credentials``.
        cluster_arn: Aurora cluster with the Data API enabled.
        master_secret_arn: Secret of a user that can create roles, schemas
            and extensions and grant ``member_of`` roles.
        database: Target database.
        role_name: Login role to create or update; uses ``schemas`` and
            applies the script.
        schema_sql_path: Script applied as ``role_name`` in one transaction.
            Write it to be re-runnable (``IF NOT EXISTS``, ``CREATE OR
            REPLACE``).
        schemas: Schemas created by the master user, with USAGE and CREATE
            granted to ``role_name`` (which owns what its script creates).
        extensions: ``[{"name": ..., "schema": ...}]``, created by the master
            user (extensions need it).
        member_of: Existing roles granted to ``role_name``.
        search_path: Set on the role in ``database``.
        create_database: Create ``database`` if it does not exist.
        maintenance_database: Database the master user connects to for role
            and database creation.
        host, port: Included in the secret for clients that connect directly.
        opts: Pulumi resource options.
    """
    return PostgresSchema(
        name,
        cluster_arn=cluster_arn,
        master_secret_arn=master_secret_arn,
        database=database,
        role_name=role_name,
        schema_sql_path=schema_sql_path,
        schemas=schemas,
        extensions=extensions,
        member_of=member_of,
        search_path=search_path,
        create_database=create_database,
        maintenance_database=maintenance_database,
        host=host,
        port=port,
        opts=opts,
    )
