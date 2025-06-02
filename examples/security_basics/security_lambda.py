import hmac
import hashlib
import base64
import json
import os
import jwt
import requests
import boto3
from botocore.exceptions import ClientError
import logging

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("LOGGING_LEVEL", "INFO"))

# Initialize the Cognito client
cognito_client = boto3.client("cognito-idp")

USER_POOL_ID = os.getenv("USER_POOL_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REGION = os.getenv("AWS_REGION", "us-east-1")
ISSUER = os.getenv(
    "ISSUER"
)  # expected format: https://cognito-idp.<region>.amazonaws.com/<user_pool_id>


def handler(event, context):
    log.info(f"event: {event}")
    action = event.get("resource")

    if action.endswith("/signup"):
        return signup(event)
    elif action.endswith("/login"):
        result = login(event)
        log.info(f"result: {result}")
        return result
    elif action.endswith("/logout"):
        return logout(event)
    elif action.endswith("/refresh-token"):
        return refresh_token(event)
    else:
        return {"statusCode": 400, "body": json.dumps({"message": "Invalid action"})}


def signup(event):
    body = json.loads(event["body"])
    log.info(f"body: {body}")
    username = body.get("username") or body.get("email")
    password = body.get("password")

    try:

        cognito_client.admin_create_user(
            UserPoolId=USER_POOL_ID,
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
            UserPoolId=USER_POOL_ID,
            Username=username,
            Password=password,
            Permanent=True,
        )

        return {"statusCode": 200, "body": json.dumps({"message": "Signup successful"})}
    except ClientError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": e.response["Error"]["Message"]}),
        }


def login(event):
    # Log all the request headers
    headers = event.get("headers", {})
    log.info(f"Request headers: {headers}")
    body = json.loads(event["body"])
    log.info(f"body: {body}")
    username = body.get("username") or body.get("email")
    password = body.get("password")
    secret_hash = calculate_secret_hash(username)

    try:
        log.info(f"username: {username}")
        response = cognito_client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
                "SECRET_HASH": secret_hash,
            },
            ClientId=CLIENT_ID,
        )

        user_info, groups = fetch_user_info(username)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "user_info": user_info,
                    "groups": groups,
                    "id_token": response["AuthenticationResult"]["IdToken"],
                    "access_token": response["AuthenticationResult"]["AccessToken"],
                    "refresh_token": response["AuthenticationResult"]["RefreshToken"],
                }
            ),
        }
    except ClientError as e:
        log.error(f"Error: {e.response}")
        return {
            "statusCode": 400,
            "body": json.dumps({"message": e.response["Error"]["Message"]}),
        }


def logout(event):
    headers = event.get("headers", {})
    log.info(f"Processing logout request with headers: {headers}")
    authorization_header = headers.get("Authorization")

    if not authorization_header:
        log.error("Authorization header is missing")
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Authorization header is required"}),
        }

    access_token = (
        authorization_header.split(" ")[1]
        if " " in authorization_header
        else authorization_header
    )
    log.info(f"Logout request received with access_token: {access_token}")

    if not access_token:
        return {"statusCode": 200, "body": json.dumps({"message": "Logout successful"})}

    try:
        response = cognito_client.global_sign_out(AccessToken=access_token)
        log.info(f"Logout response: {response}")
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            log.error("Logout failed")
            return {"statusCode": 400, "body": json.dumps({"message": "Logout failed"})}
        return {"statusCode": 200, "body": json.dumps({"message": "Logout successful"})}
    except ClientError as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": e.response["Error"]["Message"]}),
        }


def calculate_secret_hash(username):
    message = username + CLIENT_ID
    secret_hash = hmac.new(
        CLIENT_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(secret_hash).decode("utf-8")


def validate_token(event, context):
    token = event.get("headers", {}).get("Authorization", None)

    if token is None:
        return {
            "statusCode": 401,
            "body": json.dumps({"message": "Authorization header is missing"}),
        }

    try:
        # Validate the provided token
        claims = decode_token(token)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Token is valid", "user": claims}),
        }
    except Exception as e:
        return {"statusCode": 403, "body": json.dumps({"message": str(e)})}


def refresh_token(event):
    log.info("Starting refresh_token function")
    body = json.loads(event["body"])
    log.info(f"Request body: {body}")
    refresh_token = body.get("refresh_token")
    username = body.get("username")

    if not refresh_token:
        log.info("Refresh token is missing in the request")
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "Refresh token is required"}),
        }

    try:
        log.info("Attempting to use the refresh token to get new tokens")
        # Use the refresh token to get new tokens
        secret_hash = calculate_secret_hash(username)  # Calculate the secret hash
        response = cognito_client.initiate_auth(
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={
                "REFRESH_TOKEN": refresh_token,
                "SECRET_HASH": secret_hash,  # Include the secret hash
            },
            ClientId=CLIENT_ID,
        )
        log.info(f"InitiateAuth response: {response}")

        # Extract tokens from the response
        access_token = response["AuthenticationResult"]["AccessToken"]
        id_token = response["AuthenticationResult"]["IdToken"]
        new_refresh_token = response["AuthenticationResult"].get(
            "RefreshToken", refresh_token
        )  # Use the new refresh token if provided
        log.info(f"Access token: {access_token}")
        log.info(f"ID token: {id_token}")
        log.info(f"Refresh token: {new_refresh_token}")

        user_info, groups = fetch_user_info(username)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "access_token": access_token,
                    "id_token": id_token,
                    "refresh_token": new_refresh_token,
                    "user_info": user_info,
                    "groups": groups,
                }
            ),
        }
    except ClientError as e:
        log.error(f"ClientError occurred: {e.response}")
        return {
            "statusCode": 400,
            "body": json.dumps({"message": e.response["Error"]["Message"]}),
        }
    except Exception as e:
        log.error(f"Unexpected error occurred: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "An unexpected error occurred"}),
        }


def decode_token(event, token: str) -> dict:
    """
    Validate and decode the JWT token using the public key from the Cognito User Pool.
    """
    log.info("Decoding token")

    # Get the public keys from Cognito (could be improved with dynamic key fetching)
    jwks_url = f"{ISSUER}/.well-known/jwks.json"
    response = requests.get(jwks_url)
    if response.status_code != 200:
        raise Exception(f"Error fetching JWKS: {response.text}")

    jwks = response.json()

    # Load the public key corresponding to the token's kid
    header = jwt.get_unverified_header(token)
    key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    log.info(f"Public key: {public_key}")

    audience = event["methodArn"].rstrip("/").split(":")[-1].split("/")[1]
    log.info(f"Audience: {audience}")
    try:
        # Decode and verify the JWT token
        decoded_token = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=ISSUER,
        )
        return decoded_token
    except jwt.ExpiredSignatureError:
        log.error("Token has expired.")
        raise jwt.InvalidTokenError("Token has expired.")
    except jwt.InvalidTokenError as e:
        log.error(f"Token validation failed: {e}")
        raise


def fetch_user_info(username):
    # Fetch user attributes
    user_details = cognito_client.admin_get_user(
        UserPoolId=USER_POOL_ID, Username=username
    )
    attributes = {
        attr["Name"]: attr["Value"] for attr in user_details.get("UserAttributes", [])
    }
    log.info(f"User attributes: {attributes}")
    # Get the user's groups
    user_groups = cognito_client.admin_list_groups_for_user(
        UserPoolId=USER_POOL_ID, Username=username
    )
    groups = [group["GroupName"] for group in user_groups.get("Groups", [])]
    log.info(f"User groups: {groups}")

    return attributes, groups
