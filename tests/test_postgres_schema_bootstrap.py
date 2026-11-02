"""Tests for the postgres_schema bootstrap handler, with a recording fake of
the RDS Data API client."""

import json

import pytest

from cloud_foundry.services import postgres_schema_bootstrap as bootstrap


class FakeRdsData:
    class exceptions:
        class DatabaseResumingException(Exception):
            pass

    def __init__(self, existing_roles=()):
        self.calls = []
        self.existing_roles = set(existing_roles)

    def execute_statement(self, **kwargs):
        self.calls.append(
            ("execute", kwargs["database"], kwargs["sql"], kwargs.get("transactionId"))
        )
        if "FROM pg_roles" in kwargs["sql"]:
            name = kwargs["parameters"][0]["value"]["stringValue"]
            return {"records": [[1]] if name in self.existing_roles else []}
        return {"records": []}

    def begin_transaction(self, **kwargs):
        self.calls.append(("begin", kwargs["database"], kwargs["secretArn"], None))
        return {"transactionId": "tx-1"}

    def commit_transaction(self, **kwargs):
        self.calls.append(("commit", None, None, kwargs["transactionId"]))

    def rollback_transaction(self, **kwargs):
        self.calls.append(("rollback", None, None, kwargs["transactionId"]))


CONFIG = {
    "cluster_arn": "arn:cluster",
    "master_secret_arn": "arn:master",
    "role_secret_arn": "arn:role",
    "database": "candidate_evidence",
    "maintenance_database": "postgres",
    "role_name": "insight_app",
    "schemas": ["insight"],
    "extensions": [{"name": "vector", "schema": "insight"}],
    "member_of": ["cep_lens_reader"],
    "search_path": ["insight", "cep", "public"],
    "create_database": False,
}


@pytest.fixture
def fake(monkeypatch):
    client = FakeRdsData()
    monkeypatch.setattr(bootstrap, "_rds_data", client)
    return client


@pytest.mark.unit
def test_master_statements():
    assert bootstrap.master_statements(CONFIG) == [
        'GRANT CONNECT ON DATABASE "candidate_evidence" TO "insight_app"',
        'CREATE SCHEMA IF NOT EXISTS "insight"',
        'GRANT USAGE, CREATE ON SCHEMA "insight" TO "insight_app"',
        'CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "insight"',
        'GRANT "cep_lens_reader" TO "insight_app"',
        'ALTER ROLE "insight_app" IN DATABASE "candidate_evidence" '
        'SET search_path = "insight", "cep", "public"',
    ]


@pytest.mark.unit
def test_unsafe_identifier_rejected():
    with pytest.raises(ValueError):
        bootstrap.master_statements(dict(CONFIG, member_of=['x"; DROP TABLE y; --']))


@pytest.mark.unit
def test_creates_role_then_alters_it(fake):
    bootstrap.ensure_role(CONFIG, "pa'ss")
    create = [c for c in fake.calls if "ROLE" in c[2] and "LOGIN" in c[2]]
    assert create[0][2] == """CREATE ROLE "insight_app" WITH LOGIN PASSWORD 'pa''ss'"""
    assert create[0][1] == "postgres"

    fake.existing_roles.add("insight_app")
    bootstrap.ensure_role(CONFIG, "x")
    assert fake.calls[-1][2].startswith('ALTER ROLE "insight_app"')


@pytest.mark.unit
def test_schema_applied_in_one_transaction_as_role(fake):
    count = bootstrap.apply_schema(
        CONFIG,
        "CREATE TABLE a (x int);\n-- note; with semicolon\n"
        "DO $$ BEGIN PERFORM 1; END $$;\nCREATE TABLE b (y text DEFAULT ';');",
    )
    assert count == 3
    assert fake.calls[0] == ("begin", "candidate_evidence", "arn:role", None)
    assert [c[3] for c in fake.calls[1:4]] == ["tx-1"] * 3
    assert fake.calls[-1][0] == "commit"


@pytest.mark.unit
def test_failed_statement_rolls_back(fake, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("bad sql")

    monkeypatch.setattr(fake, "execute_statement", boom)
    with pytest.raises(RuntimeError):
        bootstrap.apply_schema(CONFIG, "CREATE TABLE a (x int);")
    assert fake.calls[-1][0] == "rollback"


@pytest.mark.unit
def test_config_reads_environment(monkeypatch, tmp_path):
    static = {
        k: v
        for k, v in CONFIG.items()
        if k not in ("cluster_arn", "master_secret_arn", "role_secret_arn", "database")
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(static))
    monkeypatch.setattr(bootstrap, "CONFIG_PATH", path)
    monkeypatch.setenv("CLUSTER_ARN", "arn:cluster")
    monkeypatch.setenv("MASTER_SECRET_ARN", "arn:master")
    monkeypatch.setenv("ROLE_SECRET_ARN", "arn:role")
    monkeypatch.setenv("DATABASE", "candidate_evidence")
    monkeypatch.setenv("MAINTENANCE_DATABASE", "postgres")
    assert bootstrap.load_config() == CONFIG
