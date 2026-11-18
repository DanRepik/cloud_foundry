"""The example token validator must never write the bearer token to logs
(anyone who can read CloudWatch could replay it until it expires), nor the
claims decoded from it (email, username, groups)."""

import importlib.util
import logging
from pathlib import Path

import pytest

TOKEN = "eyJhbGciOiJSUzI1NiJ9.secret-payload.secret-signature"
CLAIMS = {
    "sub": "user-1",
    "email": "alice@example.com",
    "username": "alice-login",
    "cognito:groups": ["payroll-admins"],
}


@pytest.fixture
def validator():
    path = Path(__file__).parents[1] / "examples/security_basics/token_validator.py"
    spec = importlib.util.spec_from_file_location("example_token_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "event",
    [
        {
            "type": "TOKEN",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/dev/GET/x",
            "authorizationToken": f"Bearer {TOKEN}",
        },
        {
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/dev/$connect",
            "headers": {"Sec-WebSocket-Protocol": f"auth, {TOKEN}"},
        },
    ],
)
def test_handler_logs_neither_token_nor_claims(validator, monkeypatch, caplog, event):
    monkeypatch.setattr(validator, "decode_token", lambda e, t: CLAIMS)
    caplog.set_level(logging.DEBUG)

    result = validator.handler(event, None)

    assert result["principalId"] == "user-1"
    assert caplog.records, "expected the handler to log something"
    secrets = [TOKEN, "alice@example.com", "alice-login", "payroll-admins"]
    leaked = [s for r in caplog.records for s in secrets if s in r.getMessage()]
    assert not leaked
