"""Bootstrap a Postgres login role and schema over the RDS Data API.

Deployed by ``cloud_foundry.postgres_schema``. Everything it does is fixed at
deploy time: ``config.json`` (role, schemas, extensions, role memberships,
search path) and ``schema.sql`` are bundled into the package, and the cluster,
database and secret ARNs come from the function's environment
(``CLUSTER_ARN``, ``MASTER_SECRET_ARN``, ``ROLE_SECRET_ARN``, ``DATABASE``,
``MAINTENANCE_DATABASE``). The invocation event is ignored, because with master credentials in play an
event-supplied script would let any principal that can invoke the function
run arbitrary SQL.

Steps, each idempotent:

1. As the master user, in ``maintenance_database``: create or update the
   login role with the password from its own secret, and create the target
   database if ``create_database`` is set.
2. As the master user, in the target database: grant CONNECT, create each
   schema owned by the role, create each extension in its schema, grant the
   listed roles to the role, and set its search_path.
3. As the role itself: apply ``schema.sql`` in one transaction.

The function needs no VPC attachment and no password in its environment.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
SCHEMA_SQL_PATH = HERE / "schema.sql"

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Aurora Serverless auto-pauses; the first calls after a pause raise
# DatabaseResumingException until it is back.
RESUME_RETRY_BUDGET_SECONDS = 120
RESUME_RETRY_INTERVAL_SECONDS = 5

_rds_data = None


def rds_data():
    global _rds_data
    if _rds_data is None:
        import boto3
        from botocore.config import Config

        _rds_data = boto3.client(
            "rds-data", config=Config(read_timeout=70, retries={"max_attempts": 1})
        )
    return _rds_data


_TOKEN = re.compile(
    r"""
      (?P<dollar>\$(?P<tag>[A-Za-z_][A-Za-z_0-9]*)?\$)
    | (?P<quote>'(?:[^']|'')*')
    | (?P<ident>"(?:[^"]|"")*")
    | (?P<line_comment>--[^\n]*)
    | (?P<block_comment>/\*.*?\*/)
    | (?P<semicolon>;)
    """,
    re.VERBOSE | re.DOTALL,
)


def split_statements(sql: str) -> list[str]:
    """Split a script on top-level semicolons (the Data API runs one
    statement per call). Semicolons in literals, quoted identifiers, comments
    and dollar-quoted bodies are not statement ends. Leading comments are
    stripped and comment-only fragments dropped."""
    statements: list[str] = []
    start = 0
    position = 0
    while True:
        match = _TOKEN.search(sql, position)
        if not match:
            break
        if match.group("dollar"):
            closing = sql.find(match.group("dollar"), match.end())
            if closing == -1:
                raise ValueError(
                    "Unterminated dollar-quoted body starting at offset "
                    f"{match.start()}"
                )
            position = closing + len(match.group("dollar"))
            continue
        if match.group("semicolon"):
            statements.append(sql[start : match.start()])
            start = match.end()
        position = match.end()
    statements.append(sql[start:])

    leading = re.compile(r"\A(?:\s+|--[^\n]*|/\*.*?\*/)*", re.DOTALL)
    stripped = (leading.sub("", statement).strip() for statement in statements)
    return [statement for statement in stripped if statement]


def identifier(value: str) -> str:
    if not IDENTIFIER.match(value or ""):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def literal(value: str) -> str:
    # standard_conforming_strings is on, so doubling quotes is sufficient.
    return "'" + value.replace("'", "''") + "'"


def _call(method: Callable, **kwargs) -> dict:
    deadline = time.monotonic() + RESUME_RETRY_BUDGET_SECONDS
    while True:
        try:
            return method(**kwargs)
        except rds_data().exceptions.DatabaseResumingException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(RESUME_RETRY_INTERVAL_SECONDS)


def _session(cluster_arn: str, secret_arn: str, database: str):
    target = {"resourceArn": cluster_arn, "secretArn": secret_arn, "database": database}

    def run(sql: str, parameters: Optional[list] = None) -> dict:
        kwargs = dict(target, sql=sql)
        if parameters:
            kwargs["parameters"] = parameters
        return _call(rds_data().execute_statement, **kwargs)

    def exists(sql: str, name: str) -> bool:
        params = [{"name": "n", "value": {"stringValue": name}}]
        return bool(run(sql, params).get("records"))

    return run, exists


def _secret_password(secret_arn: str) -> str:
    import boto3

    value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    return json.loads(value["SecretString"])["password"]


def master_statements(config: dict[str, Any]) -> list[str]:
    """The statements step 2 runs as the master user in the target database.
    Identifiers are validated and quoted (DDL takes no bind parameters)."""
    role = identifier(config["role_name"])
    database = identifier(config["database"])
    statements = [f"GRANT CONNECT ON DATABASE {database} TO {role}"]
    for schema in config.get("schemas", []):
        statements.append(
            f"CREATE SCHEMA IF NOT EXISTS {identifier(schema)} AUTHORIZATION {role}"
        )
    for extension in config.get("extensions", []):
        statement = f"CREATE EXTENSION IF NOT EXISTS {identifier(extension['name'])}"
        if extension.get("schema"):
            statement += f" WITH SCHEMA {identifier(extension['schema'])}"
        statements.append(statement)
    for member_of in config.get("member_of", []):
        statements.append(f"GRANT {identifier(member_of)} TO {role}")
    search_path = config.get("search_path") or []
    if search_path:
        path = ", ".join(identifier(s) for s in search_path)
        # The Data API cannot pass connection options, so search_path is
        # set on the role instead of per connection.
        statements.append(
            f"ALTER ROLE {role} IN DATABASE {database} SET search_path = {path}"
        )
    return statements


def ensure_role(config: dict[str, Any], password: str) -> None:
    run, exists = _session(
        config["cluster_arn"],
        config["master_secret_arn"],
        config.get("maintenance_database") or "postgres",
    )
    role = config["role_name"]
    verb = (
        "ALTER"
        if exists("SELECT 1 FROM pg_roles WHERE rolname = :n", role)
        else "CREATE"
    )
    run(f"{verb} ROLE {identifier(role)} WITH LOGIN PASSWORD {literal(password)}")
    if config.get("create_database") and not exists(
        "SELECT 1 FROM pg_database WHERE datname = :n", config["database"]
    ):
        # CREATE DATABASE cannot run inside a transaction; each Data API call
        # without a transactionId autocommits.
        run(f"CREATE DATABASE {identifier(config['database'])}")


def prepare_database(config: dict[str, Any]) -> list[str]:
    run, _ = _session(
        config["cluster_arn"], config["master_secret_arn"], config["database"]
    )
    statements = master_statements(config)
    for statement in statements:
        run(statement)
    return statements


def apply_schema(config: dict[str, Any], schema_sql: str) -> int:
    statements = split_statements(schema_sql)
    if not statements:
        return 0
    target = {
        "resourceArn": config["cluster_arn"],
        "secretArn": config["role_secret_arn"],
    }
    client = rds_data()
    transaction_id = _call(
        client.begin_transaction, database=config["database"], **target
    )["transactionId"]
    try:
        for statement in statements:
            _call(
                client.execute_statement,
                database=config["database"],
                sql=statement,
                transactionId=transaction_id,
                **target,
            )
    except Exception:
        client.rollback_transaction(transactionId=transaction_id, **target)
        raise
    client.commit_transaction(transactionId=transaction_id, **target)
    return len(statements)


_ENVIRONMENT = {
    "cluster_arn": "CLUSTER_ARN",
    "master_secret_arn": "MASTER_SECRET_ARN",
    "role_secret_arn": "ROLE_SECRET_ARN",
    "database": "DATABASE",
    "maintenance_database": "MAINTENANCE_DATABASE",
}


def load_config() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key, variable in _ENVIRONMENT.items():
        if os.environ.get(variable):
            config[key] = os.environ[variable]
    return config


def handler(_event: Any, _context: Any) -> dict[str, Any]:
    config = load_config()
    ensure_role(config, _secret_password(config["role_secret_arn"]))
    prepared = prepare_database(config)
    schema_sql = (
        SCHEMA_SQL_PATH.read_text(encoding="utf-8") if SCHEMA_SQL_PATH.exists() else ""
    )
    applied = apply_schema(config, schema_sql)
    return {
        "ok": True,
        "database": config["database"],
        "role": config["role_name"],
        "master_statements": len(prepared),
        "schema_statements": applied,
    }
