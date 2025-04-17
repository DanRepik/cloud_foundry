# python_function

Creates an AWS Lambda function using Pulumi with Python-specific configurations. This function simplifies the process of packaging Python code, dependencies, and configuration into a deployable Lambda function.

## Function Signature

```python
def python_function(
    name: str,
    *,
    handler: str = None,
    memory_size: int = None,
    timeout: int = None,
    sources: dict[str, str] = [],
    requirements: list[str] = [],
    policy_statements: list[str] = [],
    environment: dict[str, str] = [],
    vpc_config: dict = None,
    opts=None,
) -> Function:
```

## Parameters

| Parameter        | Type                     | Description                                                                 | Default Value |
|------------------|--------------------------|-----------------------------------------------------------------------------|---------------|
| name           | str                   | The name of the Lambda function.                                           | Required      |
| handler        | str                   | The entry point for the Lambda function (e.g., module.function). Default is 'app.handler'.       | None        |
| memory_size    | int                   | The amount of memory (in MB) allocated to the Lambda function.             | None        |
| timeout        | int                   | The maximum execution time (in seconds) for the Lambda function.           | None        |
| sources        | dict[str, str]        | A dictionary mapping source code resoures to their paths, folders, or in-line code. See notes below. | []          |
| requirements   | list[str]             | A list of Python dependencies to include in the Lambda package (e.g., ["requests", "boto3"]). | []          |
| policy_statements | list[str]          | A list of IAM policy statements to attach to the Lambda function's execution role. | []          |
| environment    | dict[str, str]        | A dictionary of environment variables to set for the Lambda function.      | []          |
| vpc_config     | dict                 | Configuration for the Lambda function's VPC (e.g., subnetIds and securityGroupIds). | None        |
| opts           | pulumi.ResourceOptions | Additional options for the Pulumi resource.                                | None        |

### Usage

### Minimal Implementation Requirements

At a minimum, a function implementation must define `sources' that specifies the Python source code for the Lambda function. Additionally, the following configurations are often required:

- **requirements**: A list of additional Python packages needed by the function (e.g., `["requests"]`).
- **environment**: A dictionary of environment variables that the function references (e.g., `{"ENV": "production"}`).
- **policy_statements**: If the function interacts with other AWS resources, access permissions must be granted through IAM policy statements.
- **vpc_config**: For resources like RDS databases, the Lambda function may need to be deployed within a specific VPC.

These configurations ensure the function has the necessary dependencies, permissions, and network access to operate effectively.

### Sources Mapping Examples

The `sources` parameter can map files, folders, and in-line code. Below are examples of each:

#### File Mapping
```python
sources = {
  "app.py": "./src/app.py"
}
```
This maps the `app.py` file from the `./src/` directory to the Lambda function.

#### Folder Mapping
```python
sources = {
  "app.py": "./src/app.py",
  "handlers/": "./src/handlers/"
}
```
This maps the entire `handlers/` folder from the `./src/` directory to the Lambda function.

#### In-line Code
```python
sources = {
  "app.py": """
def handler(event, context):
  return {
    'statusCode': 200,
    'body': 'Hello, World!'
  }
""""
}
```
This provides in-line Python code directly as a source for the Lambda function.

### Policy Statements

If the function code accesses other AWS resources, you must add policy statements to grant the necessary permissions.

Here's an example of a policy statement for a function that puts objects in an S3 bucket:

```python
policy_statements = [
  {
    "Effect": "Allow",
    "Action": ["s3:PutObject"],
    "Resource": [
      "arn:aws:s3:::your-bucket-name/*"
    ],
  }
]
```


## Returns

* Function: An instance of the Function class representing the deployed Lambda function. The returned function has the following attributes:
  - `arn`: The Amazon Resource Name (ARN) of the deployed Lambda function.
  - `invoke_arn`: The invocation ARN of the deployed Lambda function.
  - `function_name`: The name of the deployed Lambda function.
  - `function`: The AWS Lambda function object created by Pulumi.

## Example Usage

### Basic Example

```python
from cloud_foundry.pulumi.python_function import python_function

lambda_function = python_function(
    name="example-function",
    sources={
        "app.py": "./src/app.py",
    },
    environment={
        "ENV": "production",
    },
)
```

### With VPC Configuration

```python
lambda_function = python_function(
    name="vpc-function",
    handler="app.handler",
    memory_size=256,
    timeout=60,
    sources={
        "app.py": "./src/app.py",
    },
    requirements=["requests"],
    vpc_config={
        "subnetIds": ["subnet-12345678", "subnet-87654321"],
        "securityGroupIds": ["sg-12345678"],
    },
)
```

### With IAM Policy Statements

```python
lambda_function = python_function(
    name="policy-function",
    handler="app.handler",
    memory_size=128,
    timeout=15,
    sources={
        "app.py": "./src/app.py",
    },
    policy_statements=[
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": ["arn:aws:s3:::example-bucket/*"],
        },
    ],
)
```
By default, the `boto3` package is included in the AWS Lambda Python runtime. Therefore, you do not need to include it in the function's `requirements` list unless you require a specific version that differs from the runtime's default.

## How It Works

* Source Packaging:
  * The PythonArchiveBuilder is used to package the specified source files and dependencies into a deployable archive for the Lambda function.

* IAM Role and Policies:

  * The policy_statements parameter allows you to define custom IAM policies for the Lambda function's execution role.

* Environment Variables:

  * The environment parameter lets you define key-value pairs that will be available as environment variables in the Lambda runtime.

* VPC Configuration:
  * The vpc_config parameter allows you to specify VPC settings, such as subnets and security groups, for the Lambda function.


## Notes
* Ensure that the sources dictionary includes all the necessary files for the Lambda function to run.
* The requirements list should include all Python dependencies required by the Lambda function.
* If vpc_config is specified, ensure that the subnets and security groups are correctly configured for Lambda execution.
