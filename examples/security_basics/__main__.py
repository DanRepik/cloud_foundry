from cloud_foundry import python_function, rest_api
import pulumi
import pulumi_aws as aws
import os
import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION") or boto3.session.Session().region_name
ACCOUNT_ID = (
    os.getenv("AWS_ACCOUNT_ID") or boto3.client("sts").get_caller_identity()["Account"]
)
USER_POOL_ID = os.getenv("USER_POOL_ID")
print(f"ACCOUNT_ID: {ACCOUNT_ID}")

# The app client's secret, kept out of the Lambda's environment: the service
# reads it from Secrets Manager on its first call.
client_secret = aws.secretsmanager.Secret("security-client-secret")
client_secret_version = aws.secretsmanager.SecretVersion(
    "security-client-secret-version",
    secret_id=client_secret.id,
    secret_string=os.getenv("CLIENT_SECRET"),
)

# Define the security function
security_function = python_function(
    "security-function",
    # The auth service that ships with cloud_foundry; boto3 is all it needs.
    sources={
        "app.py": "pkg://cloud_foundry.services.authorization_api/security_lambda.py",
    },
    environment={
        "CLIENT_ID": os.getenv("CLIENT_ID"),
        "USER_POOL_ID": os.getenv("USER_POOL_ID"),
        "CLIENT_SECRET_ARN": client_secret.arn,
        # Admin routes (get/delete users, change groups) refuse everyone
        # until this names a Cognito group.
        "USER_ADMIN_GROUP": os.getenv("USER_ADMIN_GROUP"),
        "USER_DEFAULT_GROUP": os.getenv("USER_DEFAULT_GROUP"),
    },
    policy_statements=[
        {
            "Effect": "Allow",
            "Actions": [
                "cognito-idp:InitiateAuth",
                "cognito-idp:GlobalSignOut",
                "cognito-idp:ChangePassword",
                "cognito-idp:AdminCreateUser",
                "cognito-idp:AdminSetUserPassword",
                "cognito-idp:AdminGetUser",
                "cognito-idp:AdminDeleteUser",
                "cognito-idp:AdminListGroupsForUser",
                "cognito-idp:AdminAddUserToGroup",
                "cognito-idp:AdminRemoveUserFromGroup",
            ],
            "Resources": [
                f"arn:aws:cognito-idp:{REGION}:{ACCOUNT_ID}:userpool/{USER_POOL_ID}"
            ],
        },
        {
            "Effect": "Allow",
            "Actions": ["secretsmanager:GetSecretValue"],
            "Resources": [client_secret.arn],
        },
    ],
    opts=pulumi.ResourceOptions(depends_on=[client_secret_version]),
)

token_validator = python_function(
    "token-validator",
    sources={
        "app.py": "token_validator.py",
    },
    requirements=["pyjwt", "requests", "cryptography"],
    environment={
        "ISSUER": f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
    },
)


# Define the REST API
rest_api(
    "security-api",
    logging=True,
    specification="./security_services.yaml",
    token_validators=[
        {"type": "token_validator", "name": "auth", "function": token_validator}
    ],
    integrations=[
        {"path": path, "method": method, "function": security_function}
        for path, method in [
            ("/users", "post"),
            ("/users/{username}", "get"),
            ("/users/{username}", "delete"),
            ("/users/me/password", "put"),
            ("/users/{username}/groups", "put"),
            ("/sessions", "post"),
            ("/sessions/me", "delete"),
        ]
    ],
    export_api="s3://repik-apis/security-api.yaml",
)
