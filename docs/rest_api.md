# `rest_api` Function Documentation

The `rest_api` function is a helper method to create and configure an AWS API Gateway REST API using the RestAPI Pulumi component. It supports Lambda integrations, token validators, CORS settings, S3 content integrations, and optional logging and firewall configurations.

## Function Signature

### Parameters

- **`name`** (`str`, required):
    The name of the REST API.
    This name is used to identify the API Gateway resource and related components.

- **`body`** (`Union[str, list[str]]`, required):
    The OpenAPI specification for the API.
    Can be provided as a file path (string) or directly as a list of strings containing the OpenAPI spec.  When providing a list of strings, the specifications are merged into one based on the order.

- **`integrations`** (`list[dict]`, optional):
    A list of Lambda integrations for the API.
    Each dictionary should define:
    - `function`: The Lambda function to integrate.
    - `path`: The API path for the integration.
    - `method`: The HTTP method (e.g., `GET`, `POST`).

- **`cors_origins`** (`str`, optional):
    Enables Cross-Origin Resource Sharing (CORS) for the API if set to a truthy value.
    Specifies the allowed origins for CORS requests.

- **`token_validators`** (`list[dict]`, optional):
    A list of token validators for API authentication.
    Each dictionary can define:
    - `function`: A Lambda function to validate tokens.
    - `user_pools`: A list of Cognito User Pool ARNs for validation.

- **`firewall`** (`RestAPIFirewall`, optional):
    A firewall configuration for the API.
    Can be used to attach a WAF (Web Application Firewall) to the API Gateway.

- **`logging`** (`bool`, optional):
    Enables logging for the API Gateway stage if set to `True`.
    Logs are stored in a CloudWatch Log Group.

- **`path_prefix`** (`str`, optional):
    A prefix to prepend to all API paths.
    Useful for organizing API routes under a common base path.

### Returns

- **`RestAPI`**:
    The created RestAPI Pulumi component resource.

## Behavior

### API Gateway Creation
- Creates an API Gateway REST API using the provided OpenAPI specification or dynamically builds one based on the integrations and token validators.

### Lambda Integrations
- Configures Lambda functions as backend integrations for specific API paths and methods.

### Token Validators
- Adds token validation using either Lambda functions or Cognito User Pools.

### CORS Support
- Configures CORS settings if `cors_origins` is provided.

### Logging
- Optionally enables API Gateway stage logging to CloudWatch.

### Firewall
- Optionally attaches a Web Application Firewall (WAF) to the API Gateway.

### Outputs
- Exports the REST API ID and endpoint URL as Pulumi stack outputs.

## Example Usage

### Pulumi Outputs
- `<name>-id`:
    The ID of the created REST API.

- `<name>-host`:
    The endpoint URL of the REST API.
