"""WebSocketAPI must refuse routes that ask for auth it cannot build:
only a "lambda" authorizer is created, so anything else left the route open."""

import pytest

from cloud_foundry.pulumi.websocket_api import WebSocketAPI


def _api(authorizer):
    api = WebSocketAPI.__new__(WebSocketAPI)
    api.name = "chat"
    api.authorizer = authorizer
    api.routes = [{"route_key": "$connect", "function": "fn", "require_auth": True}]
    return api


@pytest.mark.parametrize(
    "authorizer", [None, {"type": "cognito", "user_pool_arns": ["arn"]}]
)
def test_require_auth_without_lambda_authorizer_is_rejected(authorizer):
    with pytest.raises(ValueError, match="require_auth"):
        _api(authorizer)._validate_routes()


def test_require_auth_with_lambda_authorizer_is_accepted():
    _api({"type": "lambda", "function": "auth-fn"})._validate_routes()
