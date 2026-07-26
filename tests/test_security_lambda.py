"""
Regression tests for cloud_foundry.services.authorization_api.security_lambda.

Two issues fixed here:
1. get_access_token() used to return a truthy error dict (instead of a
   falsy value) when the Authorization header was missing, so callers'
   `if not access_token: return <clean 400>` checks never triggered and a
   request with no Authorization header fell through to Cognito calls
   with a dict as the access token, raising an uncaught
   botocore.exceptions.ParamValidationError (unhandled 500) instead of a
   clean 400.
2. change_user_password() logged the plaintext new password.
"""

import json

import pytest

from cloud_foundry.services.authorization_api import (
    security_lambda as security_lambda_module,
)
from cloud_foundry.services.authorization_api.security_lambda import (
    AuthorizationServices,
)


@pytest.fixture
def auth_services():
    return AuthorizationServices(
        user_pool_id="pool-123",
        client_id="client-123",
        client_secret="secret-123",
    )


def test_get_access_token_returns_none_when_header_missing(auth_services):
    event = {"headers": {}}
    assert auth_services.get_access_token(event) is None


def test_get_access_token_extracts_bearer_token(auth_services):
    event = {"headers": {"Authorization": "Bearer abc123"}}
    assert auth_services.get_access_token(event) == "abc123"


def test_get_access_token_extracts_raw_token(auth_services):
    event = {"headers": {"Authorization": "abc123"}}
    assert auth_services.get_access_token(event) == "abc123"


def test_change_password_returns_clean_400_when_header_missing(auth_services):
    event = {
        "headers": {},
        "requestContext": {"authorizer": {"username": "alice"}},
        "body": json.dumps({"old_password": "old", "new_password": "new"}),
    }

    result = auth_services.change_user_password(event)

    assert result["statusCode"] == 400
    assert "Access token is required" in result["body"]


def test_delete_session_succeeds_when_header_missing(auth_services):
    """delete_session treats a missing token as already-logged-out."""
    event = {"headers": {}}

    result = auth_services.delete_session(event)

    assert result["statusCode"] == 200


def test_change_password_does_not_log_plaintext_password(
    auth_services, monkeypatch, caplog
):
    class FakeCognitoClient:
        def change_password(self, **kwargs):
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    monkeypatch.setattr(security_lambda_module, "cognito_client", FakeCognitoClient())

    secret_password = "sUp3rS3cr3t!"
    event = {
        "headers": {"Authorization": "Bearer abc123"},
        "requestContext": {"authorizer": {"username": "alice"}},
        "body": json.dumps(
            {"old_password": "old-password", "new_password": secret_password}
        ),
    }

    with caplog.at_level("DEBUG"):
        result = auth_services.change_user_password(event)

    assert result["statusCode"] == 200
    for record in caplog.records:
        assert secret_password not in record.getMessage()
