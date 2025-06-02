from cloud_foundry import python_function, rest_api
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

# Define the security function
security_function = python_function(
    "security-function",
    sources={
        "app.py": "security_lambda.py",
    },
    environment={
        "CLIENT_ID": os.getenv("CLIENT_ID"),
        "USER_POOL_ID": os.getenv("USER_POOL_ID"),
        "CLIENT_SECRET": os.getenv("CLIENT_SECRET"),
        "ISSUER": f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}",
    },
    requirements=["pyjwt", "requests", "cryptography"],
    policy_statements=[
        {
            "Effect": "Allow",
            "Actions": [
                "cognito-idp:SignUp",
                "cognito-idp:InitiateAuth",
                "cognito-idp:GlobalSignOut",
                "cognito-idp:AdminCreateUser",
                "cognito-idp:AdminGetUser",
                "cognito-idp:AdminSetUserPassword",
                "cognito-idp:AdminListGroupsForUser",
                "cognito-idp:GetJWKS",
            ],
            "Resources": [
                f"arn:aws:cognito-idp:{REGION}:{ACCOUNT_ID}:userpool/{USER_POOL_ID}"
            ],
        }
    ],
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
        {"path": "/signup", "method": "post", "function": security_function},
        {"path": "/login", "method": "post", "function": security_function},
        {"path": "/logout", "method": "post", "function": security_function},
        {"path": "/commitments", "method": "post", "function": security_function},
        {"path": "/refresh-token", "method": "post", "function": security_function},
    ],
    export_api="s3://repik-apis/security-api.yaml",
)
