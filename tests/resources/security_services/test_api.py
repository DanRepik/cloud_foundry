import pulumi
import pytest
import logging
import dotenv
import requests
from security_pulumi import SecurityAPI
from user_pool import UserPool
from tests.automation_helpers import deploy_stack, deploy_stack_no_teardown

log = logging.getLogger(__name__)
dotenv.load_dotenv()


def security_services_pulumi():
    def pulumi_program():
        user_pool = UserPool(
            "security-user-pool",
            self_serve=True,
            attributes=["email", "nickName"],
            groups=[
                {"description": "Admins group", "role": "admin"},
                {"description": "Users group", "role": "user"},
            ],
        )
        security_api = SecurityAPI(
            "security-api",
            client_id=user_pool.client_id,
            user_pool_id=user_pool.id,
            client_secret=user_pool.client_secret,
        )

        log.info("Security API and User Pool created successfully.")
        pulumi.export("security-api-host", security_api.domain)
        pulumi.export("token-validator", security_api.token_validator.function_name)

    return pulumi_program


@pytest.fixture(scope="module")
def security_services_stack():
    yield from deploy_stack_no_teardown("cf", "security", security_services_pulumi())


@pytest.fixture(scope="module")
def test_user():
    return {"password": "Password123!", "email": "johndoe@example.com"}


@pytest.fixture(scope="module")
def auth_tokens(security_services_stack, test_user):
    stack, outputs = security_services_stack
    domain = outputs.get("security-api-host").value

    # Ensure user exists (signup)
    requests.post(f"https://{domain}/signup", json=test_user)

    # Login to get tokens
    payload = {"username": test_user["email"], "password": test_user["password"]}
    response = requests.post(f"https://{domain}/login", json=payload)
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    assert "id_token" in data
    assert "refresh_token" in data
    return data


def test_signup(security_services_stack, test_user):
    stack, outputs = security_services_stack
    domain = outputs.get("security-api-host").value
    assert domain is not None, "Invoke URL is missing."

    log.info(f"Testing signup on domain: {domain}")
    response = requests.post(f"https://{domain}/signup", json=test_user)
    assert response.status_code == 200, f"Signup failed: {response.text}"
    data = response.json()
    assert "message" in data
    assert data["message"].lower().startswith("signup successful")


def test_logout(security_services_stack, auth_tokens):
    stack, outputs = security_services_stack
    domain = outputs.get("security-api-host").value
    log.info(f"auth_tokens x: {auth_tokens['access_token']}")
    headers = {"Authorization": f"Bearer {auth_tokens['access_token']}"}
    response = requests.post(f"https://{domain}/logout", headers=headers)
    assert response.status_code == 200, f"Logout failed: {response.text}"
    data = response.json()
    assert "message" in data
    assert data["message"].lower().startswith("logout successful")


def test_refresh_token(test_user, auth_tokens, security_services_stack):
    stack, outputs = security_services_stack
    domain = outputs.get("security-api-host").value
    payload = {
        "username": test_user["email"],
        "refresh_token": auth_tokens["refresh_token"],
    }
    response = requests.post(f"https://{domain}/refresh-token", json=payload)
    assert response.status_code == 200, f"Refresh token failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    assert "id_token" in data
    assert "refresh_token" in data
    assert "groups" in data
    assert isinstance(data["groups"], list)
