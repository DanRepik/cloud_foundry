import hmac
import hashlib
import base64
import json
import os
from typing import Optional
import boto3
from urllib.parse import unquote
from botocore.exceptions import ClientError
import logging

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("LOGGING_LEVEL", "INFO"))

# Initialize the Cognito client
cognito_client = boto3.client("cognito-idp")


# Cognito error code -> HTTP status. Other client errors stay 400, and
# Cognito's own server errors become 500.
COGNITO_STATUS = {
    "NotAuthorizedException": 401,
    "UserNotConfirmedException": 403,
    "PasswordResetRequiredException": 403,
    "UserNotFoundException": 404,
    "ResourceNotFoundException": 404,
    "UsernameExistsException": 409,
    "TooManyRequestsException": 429,
    "TooManyFailedAttemptsException": 429,
    "LimitExceededException": 429,
}


def error_response(e: ClientError, overrides: Optional[dict] = None) -> dict:
    code = e.response["Error"]["Code"]
    status = {**COGNITO_STATUS, **(overrides or {})}.get(code)
    if status is None:
        upstream = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400)
        status = 500 if upstream >= 500 else 400
    return {
        "statusCode": status,
        "body": json.dumps({"message": e.response["Error"]["Message"]}),
    }


def bad_request(message: str) -> dict:
    return {"statusCode": 400, "body": json.dumps({"message": message})}


class AuthorizationServices:
    def __init__(
        self,
        user_pool_id=None,
        client_id=None,
        client_secret=None,
        user_admin_group=None,
        user_default_group=None,
    ):
        self.user_pool_id = user_pool_id or os.getenv("USER_POOL_ID")
        self.client_id = client_id or os.getenv("CLIENT_ID")
        self.client_secret = client_secret or os.getenv("CLIENT_SECRET")
        # Preferred over CLIENT_SECRET: a Lambda's environment is readable by
        # anyone with lambda:GetFunctionConfiguration. Read on first use.
        self.client_secret_arn = os.getenv("CLIENT_SECRET_ARN")
        self.user_admin_group = user_admin_group or os.getenv("USER_ADMIN_GROUP")
        self.user_default_group = user_default_group or os.getenv("USER_DEFAULT_GROUP")
        region = os.getenv("AWS_REGION")
        self.cognito_client = boto3.client("cognito-idp", region_name=region)

    def handler(self, event, context):
        if not self.client_secret and self.client_secret_arn:
            self.client_secret = boto3.client("secretsmanager").get_secret_value(
                SecretId=self.client_secret_arn
            )["SecretString"]
        assert (
            self.user_pool_id and self.client_id and self.client_secret
        ), "USER_POOL_ID, CLIENT_ID, and CLIENT_SECRET (or CLIENT_SECRET_ARN) must be set"

        path = event.get("resource", "")
        http_method = event.get("httpMethod", "").upper()
        log.info(f"Path: {path}, HTTP Method: {http_method}")

        try:
            if path.endswith("/users") and http_method == "POST":
                return self.create_user(event)
            elif path.endswith("/users/{username}") and http_method == "GET":
                return self.get_user(event)
            elif path.endswith("/users/{username}") and http_method == "DELETE":
                return self.delete_user(event)
            elif path.endswith("/users/me/password") and http_method == "PUT":
                return self.change_user_password(event)
            elif path.endswith("/users/{username}/groups") and http_method == "PUT":
                return self.change_user_groups(event)
            elif path.endswith("/sessions") and http_method == "POST":
                return self.create_session(event)
            elif path.endswith("/sessions/me") and http_method == "DELETE":
                return self.delete_session(event)
        except json.JSONDecodeError:
            return bad_request("Request body must be JSON")
        return {
            "statusCode": 404,
            "body": json.dumps({"message": f"No route for {http_method} {path}"}),
        }

    @staticmethod
    def body(event) -> dict:
        return json.loads(event.get("body") or "{}")

    def create_user(self, event):
        body = self.body(event)
        username = body.get("username") or body.get("email")
        password = body.get("password")
        if not username or not password:
            return bad_request("username and password are required")

        try:

            cognito_client.admin_create_user(
                UserPoolId=self.user_pool_id,
                Username=username,
                UserAttributes=[
                    {"Name": "email", "Value": username},
                    {"Name": "email_verified", "Value": "true"},
                ],
                TemporaryPassword=password,
                MessageAction="SUPPRESS",
            )

            # Set the user's password to a permanent one
            cognito_client.admin_set_user_password(
                UserPoolId=self.user_pool_id,
                Username=username,
                Password=password,
                Permanent=True,
            )
            # Add user to default group if self.user_default_group is set
            if self.user_default_group:
                cognito_client.admin_add_user_to_group(
                    UserPoolId=self.user_pool_id,
                    Username=username,
                    GroupName=self.user_default_group,
                )

            return {
                "statusCode": 201,
                "body": json.dumps({"message": "Signup successful"}),
            }
        except ClientError as e:
            return error_response(e)

    def get_user(self, event):
        denied = self.require_admin(event)
        if denied:
            return denied

        username = unquote(event["pathParameters"]["username"])
        try:
            user_info, groups = self.fetch_user_info(username)
            return {
                "statusCode": 200,
                "body": json.dumps({"user_info": user_info, "groups": sorted(groups)}),
            }
        except ClientError as e:
            return error_response(e)

    def delete_user(self, event):
        denied = self.require_admin(event)
        if denied:
            return denied

        username = event["pathParameters"]["username"]
        try:
            # If username is 'me', get the actual username from the authorizer
            if username == "me":
                username = event["requestContext"]["authorizer"]["username"]
            else:
                username = unquote(username)
        except Exception:
            # If decoding fails, just use the original username
            pass

        try:
            cognito_client.admin_delete_user(
                UserPoolId=self.user_pool_id,
                Username=username,
            )
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "User deleted successfully"}),
            }
        except ClientError as e:
            log.error(f"Error deleting user: {e.response}")
            return error_response(e)

    def change_user_password(self, event):
        body = self.body(event)
        try:
            request_context = event.get("requestContext")
            username = request_context.get("authorizer", {}).get("username")
            access_token = self.get_access_token(event)
            if not access_token:
                return {
                    "statusCode": 400,
                    "body": json.dumps(
                        {"message": "Access token is required to change password"}
                    ),
                }
            old_password = body.get("old_password")
            if not old_password:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"message": "Old password is required"}),
                }

            new_password = body.get("new_password")
            log.info(f"Changing password for user: {username}")

            result = cognito_client.change_password(
                PreviousPassword=old_password,
                ProposedPassword=new_password,
                AccessToken=access_token,
            )
            if result["ResponseMetadata"]["HTTPStatusCode"] != 200:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"message": "Password change failed"}),
                }

            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Password changed successfully"}),
            }
        except ClientError as e:
            return error_response(e)

    def change_user_groups(self, event):
        denied = self.require_admin(event)
        if denied:
            return denied

        username = unquote(event["pathParameters"]["username"])
        body = self.body(event)
        groups = body.get("groups", [])

        try:
            current_groups = set(self.fetch_user_info(username)[1])
            new_groups = set(groups)

            # Remove user from groups they are no longer in
            for group in current_groups - new_groups:
                cognito_client.admin_remove_user_from_group(
                    UserPoolId=self.user_pool_id,
                    Username=username,
                    GroupName=group,
                )

            # Add user to new groups they are not already in
            for group in new_groups - current_groups:
                cognito_client.admin_add_user_to_group(
                    UserPoolId=self.user_pool_id,
                    Username=username,
                    GroupName=group,
                )

            return {
                "statusCode": 200,
                "body": json.dumps({"message": "User groups updated successfully"}),
            }
        except ClientError as e:
            # AdminAddUserToGroup reports an unknown group as ResourceNotFound.
            return error_response(e, {"ResourceNotFoundException": 400})

    def create_session(self, event):
        """Start a session with a password, or renew one with a refresh token
        (one resource, two grants, like an OAuth token endpoint)."""
        body = self.body(event)
        username = body.get("username") or body.get("email")
        if not username:
            return bad_request("username is required")
        if body.get("refresh_token"):
            flow = "REFRESH_TOKEN_AUTH"
            params = {"REFRESH_TOKEN": body["refresh_token"]}
        elif body.get("password"):
            flow = "USER_PASSWORD_AUTH"
            params = {"USERNAME": username, "PASSWORD": body["password"]}
        else:
            return bad_request("password or refresh_token is required")

        try:
            # A refresh's SECRET_HASH must use the user's Cognito username;
            # in a pool that signs in by email that is the sub, not the email.
            hash_name = (
                cognito_client.admin_get_user(
                    UserPoolId=self.user_pool_id, Username=username
                )["Username"]
                if flow == "REFRESH_TOKEN_AUTH"
                else username
            )
            params["SECRET_HASH"] = self.calculate_secret_hash(hash_name)
            response = cognito_client.initiate_auth(
                AuthFlow=flow, AuthParameters=params, ClientId=self.client_id
            )
            tokens = response["AuthenticationResult"]
            user_info, groups = self.fetch_user_info(username)
        except ClientError as e:
            log.error(f"{flow} failed: {e.response['Error']['Code']}")
            # An unknown user is a failed login, not a 404 that tells a
            # caller which usernames exist.
            return error_response(e, {"UserNotFoundException": 401})

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "user_info": user_info,
                    "groups": groups,
                    "id_token": tokens["IdToken"],
                    "access_token": tokens["AccessToken"],
                    # A refresh returns no new refresh token; keep the old one.
                    "refresh_token": tokens.get(
                        "RefreshToken", body.get("refresh_token")
                    ),
                }
            ),
        }

    def delete_session(self, event):
        try:
            access_token = self.get_access_token(event)
            if not access_token:
                return {
                    "statusCode": 200,
                    "body": json.dumps({"message": "Logout successful"}),
                }

            response = cognito_client.global_sign_out(AccessToken=access_token)
            if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"message": "Logout failed"}),
                }
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Logout successful"}),
            }
        except ClientError as e:
            return error_response(e)

    def calculate_secret_hash(self, username):
        message = username + self.client_id
        secret_hash = hmac.new(
            self.client_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.b64encode(secret_hash).decode("utf-8")

    def fetch_user_info(self, username):
        # Fetch user attributes
        user_details = cognito_client.admin_get_user(
            UserPoolId=self.user_pool_id, Username=username
        )
        attributes = {
            attr["Name"]: attr["Value"]
            for attr in user_details.get("UserAttributes", [])
        }
        # Get the user's groups
        user_groups = cognito_client.admin_list_groups_for_user(
            UserPoolId=self.user_pool_id, Username=username
        )
        groups = [group["GroupName"] for group in user_groups.get("Groups", [])]

        return attributes, groups

    def require_admin(self, event) -> Optional[dict]:
        """403 response unless the caller is in the admin group. Fails closed:
        with no USER_ADMIN_GROUP configured nobody gets admin actions, since
        otherwise any signed-in user could delete users or grant themselves
        any group."""
        if self.user_admin_group and self.user_admin_group in (
            self.get_permissions_from_event(event)
        ):
            return None
        return {
            "statusCode": 403,
            "body": json.dumps({"message": "Admin permission required"}),
        }

    def get_permissions_from_event(self, event):
        """
        Extracts permissions from a decoded JWT token.
        Looks for 'permissions', 'scope', or 'cognito:groups' claims.
        Returns a list of permissions.
        """
        import re

        def to_list(x):
            if isinstance(x, str):
                x = x.strip()
                # Authorizer context values must be strings, so a token
                # validator passes a list as JSON ('["admin"]').
                if x.startswith("["):
                    return to_list(json.loads(x))
                return re.split(r"[,\s]+", x)
            elif isinstance(x, list):
                return x
            else:
                return []

        authorizer = event.get("requestContext", {}).get("authorizer", {})

        # Check for a 'permissions' claim (custom claim)
        if "permissions" in authorizer:
            return to_list(authorizer["permissions"])
        # Check for OAuth2 'scope' claim
        if "scope" in authorizer:
            return to_list(authorizer["scope"])
        # Check for Cognito groups
        if "cognito:groups" in authorizer:
            return to_list(authorizer["cognito:groups"])
        # No permissions found
        return []

    def get_access_token(self, event) -> Optional[str]:
        """
        Extracts the access token from the event. Returns None if the
        Authorization header is missing, so callers' `if not access_token`
        checks behave correctly.
        """
        # Header names arrive in whatever case the client (or CloudFront,
        # or HTTP/2's lower case) sent.
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        authorization_header = headers.get("authorization")

        if not authorization_header:
            log.error("Authorization header is missing")
            return None

        return (
            authorization_header.split(" ")[1]
            if " " in authorization_header
            else authorization_header
        )


authorization_services = AuthorizationServices()


def handler(event, context):
    return authorization_services.handler(event, context)
