from time import sleep
import pytest
import contextlib
import logging
import dotenv
import boto3
import uuid
import os
import json
import pulumi
import urllib.parse
from user_pool import UserPool
from tests.automation_helpers import deploy_stack, deploy_stack_no_teardown
from security_lambda import AuthorizationServices

log = logging.getLogger(__name__)
dotenv.load_dotenv()


def user_pool_pulumi():
    def pulumi_program():
        user_pool = UserPool(
            "security-user-pool",
            self_serve=True,
            attributes=["username", "nickName"],
            groups=[
                {"description": "Admins group", "role": "admin"},
                {"description": "Manager group", "role": "manager"},
                {"description": "Member group", "role": "member"},
            ],
        )
        log.info("Security API and User Pool created successfully.")
        pulumi.export("user-pool-id", user_pool.id)
        pulumi.export("user-pool-client-id", user_pool.client_id)
        pulumi.export("user-pool-client-secret", user_pool.client_secret)

    return pulumi_program


@pytest.fixture(scope="module")
def user_pool_stack():
    log.info("Starting deployment of security services stack")
    yield from deploy_stack_no_teardown("cf", "security-func", user_pool_pulumi())


@pytest.fixture(scope="module")
def authorization_services(user_pool_stack):
    stack, outputs = user_pool_stack
    log.info(f"Stack outputs: {outputs}")
    service = AuthorizationServices(
        user_pool_id=outputs.get("user-pool-id").value,
        client_id=outputs.get("user-pool-client-id").value,
        client_secret=outputs.get("user-pool-client-secret").value,
        user_admin_group="admin",
        user_default_group="member",
    )
    yield service


def create_user(service, member_payload):
    log.info(f"Creating user with payload: {member_payload}")
    event = make_event(
        path="/users",
        method="POST",
        body={
            "username": member_payload["username"],
            "password": member_payload["password"],
        },
    )
    return service.handler(event, None)


def delete_user(service, access_token, username="me"):
    log.info(f"Deleting user: {username} with access token: {access_token}")

    # Use /users/me if deleting the current user, otherwise use the username
    if username == "me":
        url = "/users/me "
    else:
        url = "/users/{username}"

    event = make_event(
        path=url,
        method="DELETE",
        headers={"Authorization": f"Bearer {access_token}"},
        path_parameters={"username": urllib.parse.quote(username)},
        authorizer_context={"permissions": ["admin"]},
    )

    log.info(f"event: {event}")
    response = service.handler(event, None)
    log.info(f"response {response}")
    assert response["statusCode"] == 200


@contextlib.contextmanager
def member_user(service):
    try:
        member_payload = {
            "username": f"apitestmember_{uuid.uuid4()}@example.com",
            "password": "MemberPass1234!",
        }

        log.info(
            f"Creating admin user: {member_payload['username']} in user pool: {service.user_pool_id}"
        )
        create_user(service, member_payload)

        yield member_payload
    finally:
        with admin_user(service) as admin:
            with user_session(service, admin["username"], admin["password"]) as (
                access_token,
                _,
            ):
                delete_user(service, access_token, member_payload["username"])


@contextlib.contextmanager
def admin_user(service):
    try:
        admin_payload = {
            "username": f"apitestadmin_{uuid.uuid4()}@example.com",
            "password": "AdminPass1234!",
        }

        create_user(service, admin_payload)
        log.info(
            f"Creating admin user: {admin_payload['username']} in user pool: {service.user_pool_id}"
        )

        # Add user to admin group
        client = boto3.client("cognito-idp")
        client.admin_add_user_to_group(
            UserPoolId=service.user_pool_id,
            Username=admin_payload["username"],
            GroupName="admin",
        )

        yield admin_payload

    finally:
        # Cleanup: delete the user
        try:
            client.admin_delete_user(
                UserPoolId=service.user_pool_id, Username=admin_payload["username"]
            )
        except Exception:
            pass


@contextlib.contextmanager
def user_session(service, username, password):
    log.info(f"Logging in user {username}")

    access_token = None
    refresh_token = None
    try:
        event = make_event(
            path="/sessions",
            method="POST",
            body={"username": username, "password": password},
        )
        response = service.handler(event, None)
        log.info(f"Login user {username} response: {response}")
        assert response["statusCode"] == 200
        tokens = json.loads(response["body"])
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        log.info(f"User {username} logged in successfully")
        yield access_token, refresh_token
    finally:
        log.info(f"Logging out {username}")
        if access_token:

            event = make_event(
                path="/sessions/me",
                method="DELETE",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response = service.handler(event, None)
            log.info(f"Logout response: {response}")
            assert response["statusCode"] == 200
        log.info(f"User {username} session ended")


def make_event(
    path, method, headers=None, body=None, path_parameters=None, authorizer_context=None
):
    return {
        "resource": path,
        "httpMethod": method,
        "headers": headers or {},
        "body": json.dumps(body) if body else None,
        "requestContext": {"authorizer": authorizer_context or {}},
        "pathParameters": path_parameters or {},
    }


def test_create_and_login_user(authorization_services):
    # Setup
    username = f"apitest_{uuid.uuid4()}@example.com"
    password = "InitialPass123!"

    response = create_user(
        authorization_services, {"username": username, "password": password}
    )
    assert response["statusCode"] == 201

    with user_session(authorization_services, username, password) as (
        access_token,
        refresh_token,
    ):
        assert access_token is not None
        assert refresh_token is not None


def test_delete_user(authorization_services):
    member_payload = {
        "username": f"apitestmember_{uuid.uuid4()}@example.com",
        "password": "InitialPass123!",
    }
    create_user(authorization_services, member_payload)

    with admin_user(authorization_services) as admin:
        with user_session(
            authorization_services, admin["username"], admin["password"]
        ) as (access_token, _):
            delete_user(
                authorization_services, access_token, member_payload["username"]
            )

    # attempt to login, should fail
    event = make_event(
        path="/sessions",
        method="POST",
        body={
            "username": member_payload["username"],
            "password": member_payload["password"],
        },
    )
    response = authorization_services.handler(event, None)
    assert response["statusCode"] != 200


def test_change_password(authorization_services):
    with member_user(authorization_services) as member:
        new_password = "NewPass12345!"
        with user_session(
            authorization_services, member["username"], member["password"]
        ) as (access_token, _):
            event = make_event(
                path="/users/me/password",
                method="PUT",
                headers={"Authorization": f"Bearer {access_token}"},
                body={"old_password": member["password"], "new_password": new_password},
                authorizer_context={
                    "permissions": ["member"],
                    "username": member["username"],
                },
            )
            response = authorization_services.handler(event, None)
            assert response["statusCode"] == 200

        with user_session(authorization_services, member["username"], new_password) as (
            access_token,
            _,
        ):
            sleep(10)  # wait for eventual consistency
            assert access_token is not None


def test_get_user(authorization_services):
    member_payload = {
        "username": f"apitestmember_{uuid.uuid4()}@example.com",
        "password": "InitialPass123!",
    }
    create_user(authorization_services, member_payload)

    with admin_user(authorization_services) as admin:
        with user_session(
            authorization_services, admin["username"], admin["password"]
        ) as (access_token, _):
            response = authorization_services.handler(
                make_event(
                    path="/users/{username}",
                    method="GET",
                    headers={"Authorization": f"Bearer {access_token}"},
                    path_parameters={
                        "username": urllib.parse.quote(member_payload["username"])
                    },
                    authorizer_context={"permissions": ["admin"]},
                ),
                None,
            )
            log.info(f"Get user response: {response}")
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            log.info(f"user_info: {body}")
            log.info(f"user_info: {body["user_info"]}")
            assert body["user_info"]["email"] == member_payload["username"]
            assert body["groups"] == ["member"]
            delete_user(
                authorization_services, access_token, member_payload["username"]
            )


def test_change_groups(authorization_services):
    with member_user(authorization_services) as member:
        with admin_user(authorization_services) as admin:
            with user_session(
                authorization_services, admin["username"], admin["password"]
            ) as (access_token, _):
                response = authorization_services.handler(
                    make_event(
                        path="/users/{username}",
                        method="GET",
                        headers={"Authorization": f"Bearer {access_token}"},
                        path_parameters={
                            "username": urllib.parse.quote(member["username"])
                        },
                        authorizer_context={"permissions": ["admin"]},
                    ),
                    None,
                )
                log.info(f"Get user info response: {response}")
                assert response["statusCode"] == 200
                body = json.loads(response["body"])
                log.info(f"user info body: {body}")
                assert body["groups"] == ["member"]

                sleep(10)

                # add a role
                response = authorization_services.handler(
                    make_event(
                        path="/users/{username}/groups",
                        method="PUT",
                        body={"groups": ["member", "manager"]},
                        headers={"Authorization": f"Bearer {access_token}"},
                        path_parameters={
                            "username": urllib.parse.quote(member["username"])
                        },
                        authorizer_context={"permissions": ["admin"]},
                    ),
                    None,
                )
                assert response["statusCode"] == 200

                sleep(10)

                response = authorization_services.handler(
                    make_event(
                        path="/users/{username}",
                        method="GET",
                        headers={"Authorization": f"Bearer {access_token}"},
                        path_parameters={
                            "username": urllib.parse.quote(member["username"])
                        },
                        authorizer_context={"permissions": ["admin"]},
                    ),
                    None,
                )
                assert response["statusCode"] == 200
                body = json.loads(response["body"])
                log.info(f"body: {body}")
                assert body["groups"] == ["member", "manager"]

                # add a role
                response = authorization_services.handler(
                    make_event(
                        path="/users/{username}/groups",
                        method="PUT",
                        body={"groups": ["member"]},
                        headers={"Authorization": f"Bearer {access_token}"},
                        path_parameters={
                            "username": urllib.parse.quote(member["username"])
                        },
                        authorizer_context={"permissions": ["admin"]},
                    ),
                    None,
                )
                assert response["statusCode"] == 200
                log.info(f"Get user response: {response}")

                sleep(10)

                response = authorization_services.handler(
                    make_event(
                        path="/users/{username}",
                        method="GET",
                        headers={"Authorization": f"Bearer {access_token}"},
                        path_parameters={
                            "username": urllib.parse.quote(member["username"])
                        },
                        authorizer_context={"permissions": ["admin"]},
                    ),
                    None,
                )
                assert response["statusCode"] == 200
                body = json.loads(response["body"])
                log.info(f"body: {body}")
                assert body["groups"] == ["member"]

                assert False
    #            delete_user(authorization_services, access_token, member_payload["username"])


def test_refresh_token(authorization_services):
    with member_user(authorization_services) as member:
        with user_session(
            authorization_services, member["username"], member["password"]
        ) as (access_token, refresh_token):
            event = make_event(
                path="/sessions/refresh",
                method="POST",
                body={"refresh_token": refresh_token},
                authorizer_context={
                    "permissions": ["member"],
                    "username": member["username"],
                },
            )
            response = authorization_services.handler(event, None)
            assert response["statusCode"] == 200
            tokens = json.loads(response["body"])
            assert "access_token" in tokens
            assert "refresh_token" in tokens
