# Securing Your API with the `rest_api` Function: A Step-by-Step Guide

In the prior installment of this series demonstated using the Cloud foundry `rest_api` to build a greet API offering a simple 'Hello world' service.  There the focus was to illustrate the basics of exposing a `python_function` as a service in a Rest API.

With the 'hello World' service we could safely neglect security leaving the API services publically available on the Internet.  In real world applications openly available services like that are the exception rather than the norm.

In this installment we'll explore adding security to API services.  Request authorization for API gateways is token based, where the client includes a bearer token in the authorization header in the request.  The Gateway API then validates the supplied token usually with a Lambda function.  Typically the token is a JWT token and the request is authorized if the token can be successfully decoded.  Additonally the validation function can pass the unencoded token contents to the service function allowing the function to enforce any additional fine grained access control if needed.

The process of securing PAI path operations involves two steps:

1. Setting up token validators in the `rest_api` function.
2. Updating the OpenAPI specification to enforce security on your API endpoints.

## Step 1: Setting Up Token Validators

The `rest_api` function allows you to configure token validators that the gateway will use to authenticate and authorize API requests. Token validators can be implemented using AWS Cognito User Pools or custom Lambda functions.

### Understanding the `token_validators` Argument

The `token_validators` argument in the `rest_api` function defines how incoming API requests are authenticated and authorized. Each token validator links a security schema name to a specific validation mechanism, such as an AWS Cognito User Pool or a custom Lambda function. This allows you to support multiple authentication methods for different API path operations.

Each token validator is a dictionary with the following keys:

- **`name`**: A unique name for the token validator, referenced in the OpenAPI specification.
- **`user_pools`** (optional): A list of ARNs for AWS Cognito User Pools, used for Cognito-based authentication.
- **`function`** (optional): The name of a custom Lambda function for token validation.

> **Note**: Specify either `user_pools` or `function`, but not both, to avoid configuration errors.

#### Example: Using Cognito User Pools

```python
token_validators = [
    {
        "name": "cognito-validator",
        "user_pools": ["arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_AbCdEfGhI"],
    }
]
```

#### Example: Using a Custom Lambda Function

```python
token_validators = [
    {
        "name": "lambda-validator",
        "function": my_auth_lambda_function,
    }
]
```

#### Adding Token Validators to the API

Include the `token_validators` list in the `rest_api` definition:

```python
api = rest_api(
    name="secure-api",
    specification="./api_spec.yaml",
    token_validators=token_validators,
)
```

## Step 2: Updating the OpenAPI Specification

With the token validators configured, the next step is to update the application OpenAPI specification to enforce security on specific API endpoints. This involves defining security requirements for the relevant path operations using the OpenAPI schema.

For example:

```yaml
paths:
    /secure-greet:
        get:
            summary: A secure greeting endpoint
            security:
                - cognito: []  # Matches the token validator name
            responses:
                '200':
                    description: Successful response
```

The OpenAPI specification allows `security` to be defined at the root level in the specification document. When defined at this level, the specified security requirements apply to all path operations in the API by default. This eliminates the need to explicitly define `security` for each individual path operation, simplifying the specification and ensuring consistent security enforcement across the API.  If specific path operations need different or no security requirements, they can override the root-level `security` definition by specifying their own `security` settings.

## Step 3: Deploy and Test

With including the token_validators the `__main__.py` now is;

```python
# __main__.py

import os
import cloud_foundry
from dotenv import load_dotenv

load_dotenv()

greet_function = cloud_foundry.python_function(
    "greet-function", sources={"app.py": "./app.py"}
)

greet_api = cloud_foundry.rest_api(
    "greet-api",
#    specification=["api_spec.yaml", "s3://repik-apis/security-api.yaml"],
    specification="api_spec.yaml",
    integrations=[{"path": "/greet", "method": "get", "function": greet_function}],
    token_validators=[
        { "name": "auth",
         "user_pools": [ os.environ.get("USER_POOL_ARN") ],}
    ],
    hosted_zone_id=os.environ.get("HOSTED_ZONE_ID"),
)
```

This can be deployed using;

```
pulumi up -y
```

Since a hosted zone id was provided the API gateway deployed by the `rest_api` function is accessiable as a subdomain of the hosted zone.  The subdomain by default is the project and stack name, in this case `secure-greet-dev'

The deployment can be tested

```python
# Define the /greet endpoint URL
greet_url = f"{host}/greet"

# Example 1: Without Authorization Header (Expected to Fail)
response_without_auth = requests.get(greet_url)
print("Without Authorization Header:")
print("Status Code:", response_without_auth.status_code)
print("Response:", response_without_auth.text)

# Example 2: With Authorization Header (Expected to Succeed)
headers_with_auth = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}
response_with_auth = requests.get(greet_url, headers=headers_with_auth)
print("\nWith Authorization Header:")
print("Status Code:", response_with_auth.status_code)
print("Response:", response_with_auth.text)
```
