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


@pytest.mark.parametrize("name", ["authorization", "AUTHORIZATION"])
def test_get_access_token_ignores_header_case(auth_services, name):
    event = {"headers": {name: "Bearer abc123"}}
    assert auth_services.get_access_token(event) == "abc123"


def test_get_access_token_with_null_headers(auth_services):
    assert auth_services.get_access_token({"headers": None}) is None


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


def _admin_event(groups):
    return {
        "resource": "/users/{username}",
        "httpMethod": "DELETE",
        "headers": {},
        "pathParameters": {"username": "alice"},
        "requestContext": {"authorizer": {"cognito:groups": groups}},
        "body": json.dumps({"groups": ["admin"]}),
    }


@pytest.mark.parametrize("action", ["get_user", "delete_user", "change_user_groups"])
def test_admin_actions_denied_when_no_admin_group_configured(auth_services, action):
    # Fail closed: without USER_ADMIN_GROUP nobody may run admin actions.
    result = getattr(auth_services, action)(_admin_event("admin"))
    assert result["statusCode"] == 403


@pytest.mark.parametrize("action", ["get_user", "delete_user", "change_user_groups"])
def test_admin_actions_denied_for_non_admin(action):
    services = AuthorizationServices(
        "pool", "client", "secret", user_admin_group="admin"
    )
    result = getattr(services, action)(_admin_event("user"))
    assert result["statusCode"] == 403


def test_admin_can_delete_user(monkeypatch):
    deleted = []

    class FakeCognitoClient:
        def admin_delete_user(self, **kwargs):
            deleted.append(kwargs["Username"])

    monkeypatch.setattr(security_lambda_module, "cognito_client", FakeCognitoClient())
    services = AuthorizationServices(
        "pool", "client", "secret", user_admin_group="admin"
    )

    result = services.delete_user(_admin_event("admin"))

    assert result["statusCode"] == 200
    assert deleted == ["alice"]


def test_admin_group_read_from_json_encoded_authorizer_context():
    # examples/security_basics/token_validator.py sends json.dumps(groups).
    services = AuthorizationServices(
        "pool", "client", "secret", user_admin_group="admin"
    )
    event = {"requestContext": {"authorizer": {"permissions": '["user", "admin"]'}}}
    assert services.require_admin(event) is None


def test_handler_does_not_log_request_body(auth_services, monkeypatch, caplog):
    event = {
        "resource": "/nope",
        "httpMethod": "POST",
        "body": json.dumps({"password": "sUp3rS3cr3t!"}),
    }
    with caplog.at_level("DEBUG"):
        auth_services.handler(event, None)
    assert all("sUp3rS3cr3t!" not in r.getMessage() for r in caplog.records)


def _client_error(code, http_status=400):
    from botocore.exceptions import ClientError

    return ClientError(
        {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": http_status},
        },
        "Op",
    )


@pytest.mark.parametrize(
    "code, http_status, expected",
    [
        ("UsernameExistsException", 400, 409),
        ("NotAuthorizedException", 400, 401),
        ("UserNotFoundException", 400, 404),
        ("TooManyRequestsException", 400, 429),
        ("InvalidPasswordException", 400, 400),
        ("InternalErrorException", 500, 500),
    ],
)
def test_cognito_errors_map_to_http_status(code, http_status, expected):
    from cloud_foundry.services.authorization_api.security_lambda import error_response

    assert error_response(_client_error(code, http_status))["statusCode"] == expected


class FakeAuthClient:
    """Records initiate_auth calls; raises `error` from it when set."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"AuthenticationResult": {"IdToken": "id", "AccessToken": "access"}}

    def admin_get_user(self, **kwargs):
        # An email-sign-in pool: the Cognito username is the sub.
        return {
            "Username": "sub-1",
            "UserAttributes": [{"Name": "email", "Value": "a@b.c"}],
        }

    def admin_list_groups_for_user(self, **kwargs):
        return {"Groups": [{"GroupName": "user"}]}


def _session_event(body):
    return {"resource": "/sessions", "httpMethod": "POST", "body": json.dumps(body)}


def test_refresh_token_renews_session_on_post_sessions(auth_services, monkeypatch):
    client = FakeAuthClient()
    monkeypatch.setattr(security_lambda_module, "cognito_client", client)

    result = auth_services.handler(
        _session_event({"username": "a@b.c", "refresh_token": "r1"}), None
    )

    assert result["statusCode"] == 200
    assert client.calls[0]["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert client.calls[0]["AuthParameters"]["REFRESH_TOKEN"] == "r1"
    # Hashed with the Cognito username, not the email the caller sent.
    assert client.calls[0]["AuthParameters"][
        "SECRET_HASH"
    ] == auth_services.calculate_secret_hash("sub-1")
    # Cognito returns no new refresh token on refresh; the old one stays valid.
    assert json.loads(result["body"])["refresh_token"] == "r1"


@pytest.mark.parametrize("code", ["NotAuthorizedException", "UserNotFoundException"])
def test_failed_login_is_401_without_revealing_unknown_users(
    auth_services, monkeypatch, code
):
    monkeypatch.setattr(
        security_lambda_module, "cognito_client", FakeAuthClient(_client_error(code))
    )
    result = auth_services.handler(
        _session_event({"username": "a@b.c", "password": "pw"}), None
    )
    assert result["statusCode"] == 401


def test_session_without_password_or_refresh_token_is_400(auth_services):
    result = auth_services.handler(_session_event({"username": "a@b.c"}), None)
    assert result["statusCode"] == 400


def test_unknown_route_is_404(auth_services):
    event = {"resource": "/sessions/refresh", "httpMethod": "POST", "body": "{}"}
    assert auth_services.handler(event, None)["statusCode"] == 404


def test_malformed_json_body_is_400(auth_services):
    event = {"resource": "/users", "httpMethod": "POST", "body": "{not json"}
    assert auth_services.handler(event, None)["statusCode"] == 400


def test_signup_with_taken_username_is_409(auth_services, monkeypatch):
    class TakenClient:
        def admin_create_user(self, **kwargs):
            raise _client_error("UsernameExistsException")

    monkeypatch.setattr(security_lambda_module, "cognito_client", TakenClient())
    event = {
        "resource": "/users",
        "httpMethod": "POST",
        "body": json.dumps({"username": "a@b.c", "password": "pw"}),
    }
    assert auth_services.handler(event, None)["statusCode"] == 409


def test_password_login_hashes_the_name_given(auth_services, monkeypatch):
    client = FakeAuthClient()
    monkeypatch.setattr(security_lambda_module, "cognito_client", client)

    auth_services.handler(_session_event({"email": "a@b.c", "password": "pw"}), None)

    assert client.calls[0]["AuthParameters"][
        "SECRET_HASH"
    ] == auth_services.calculate_secret_hash("a@b.c")


def test_client_secret_read_once_from_secrets_manager(monkeypatch):
    reads = []

    class FakeSecrets:
        def get_secret_value(self, SecretId):
            reads.append(SecretId)
            return {"SecretString": "from-sm"}

    monkeypatch.setenv("CLIENT_SECRET_ARN", "arn:secret")
    monkeypatch.delenv("CLIENT_SECRET", raising=False)
    services = AuthorizationServices(user_pool_id="pool-123", client_id="client-123")
    monkeypatch.setattr(
        security_lambda_module.boto3,
        "client",
        lambda name, **kw: FakeSecrets() if name == "secretsmanager" else None,
    )
    monkeypatch.setattr(security_lambda_module, "cognito_client", FakeAuthClient())

    for _ in range(2):
        services.handler(_session_event({"email": "a@b.c", "password": "pw"}), None)

    assert services.client_secret == "from-sm"
    assert reads == ["arn:secret"]
