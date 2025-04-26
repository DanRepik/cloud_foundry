# Streamlining AWS Lambda Deployment with `python_function`

When deploying cloud-native applications, managing Lambda functions often becomes a tangle of zipping files, configuring permissions, and handling packaging nuances. The `python_function` utility comes from Cloud Foundry, which is curated toolkit of components built to simplify cloud-centric application development. Think of it as a modular collection of building blocks—each one purpose-built to help launch reliable services faster. With `python_function`, what used to be a mess of manual steps becomes a clean, declarative experience.

---

## Why Deployment Gets Messy

Traditional AWS Lambda deployment using the AWS Console or CLI can be tedious:

- Assemble and compress the source code
- Write IAM roles and policies
- Inject environment variables via multiple menus
- Install and bundle dependencies
- Configure VPC settings through trial and error

For projects that evolve quickly or span multiple environments, these manual steps don't just slow you down—they become costly and error-prone. Most of this deployment process can be automated, and with tools like `python_function`, it’s easy to establish a simple, repeatable workflow. For large projects, having this level of consistency not only saves time but also reduces overhead and boosts confidence in every release.

---

## Enter `python_function`: Simplicity Meets Power

The `python_function` component abstracts the boilerplate away, offering a clean Python-native interface to:

- Bundle your code and dependencies
- Define environment variables
- Attach IAM policies
- Configure VPC settings, if needed

All in one step.

### 🧱 Minimal Example

Here's a complete Lambda deployment in just a few lines of code:

```python
from cloud_foundry import python_function

lambda_function = cloud_foundry.python_function(
    name="example-function",
    sources={
        "app.py": """
import os
import json

def handler(event, context):
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f\"Hello from {os.environ.get('ENV', 'unknown')}!\"
        }),
        'headers': {
            'Content-Type': 'application/json'
        }
    }
""",
    environment={
        "ENV": "production",
    },
)
```

The result? A deployable Lambda with source code, environment config, and deployment orchestration—all automated by Cloud Foundry.

## Developer-Friendly Source Packaging

One of the standout features is the flexible `sources` parameter. It supports:

- 📄 Single file: `{ "app.py": "./src/app.py" }`
- 📁 Folder inclusion: `{ "handlers/": "./src/handlers/" }`
- 🧬 In-line code: `{ "app.py": """def handler(...): ...""" }`

This makes it easy to integrate into any CI/CD pipeline without needing additional packaging tools.

## Including Python Dependencies

In addition to source code, your Lambda function may depend on external Python packages. You can specify these using the `requirements` parameter, just like a `requirements.txt` file:

```python
requirements=[
    "requests",
    "boto3==1.26.0"
]
```

Cloud Foundry automatically installs these packages and bundles them along with your function's code, so there's no need to pre-package dependencies manually. This ensures your Lambda has everything it needs to run in AWS without additional build steps.

You can also pin versions to ensure compatibility across environments or leave them unpinned for flexibility during development.

## IAM Policies Without the Pain

Need to grant your function access to specific AWS services like S3 or DynamoDB? With `python_function`, you can do it declaratively with inline IAM policy statements:

### 🛡 IAM Policy Example

```python
lambda_function = cloud_foundry.python_function(
    name="policy-function",
    sources={"app.py": "./src/app.py"},
    policy_statements=[
        {
            "Effect": "Allow",
            "Actions": ["s3:PutObject", "s3:GetObject"],
            "Resources": ["arn:aws:s3:::example-bucket/*"],
        },
    ],
)
```

## Add VPC

Need access to a database inside a VPC? Just declare your networking config:

### 🔐 VPC Access Example

```python
lambda_function = cloud_foundry.python_function(
    name="vpc-function",
    sources={"app.py": "./src/app.py"},
    requirements=["requests"],
    vpc_config={
        "subnetIds": ["subnet-12345678", "subnet-87654321"],
        "securityGroupIds": ["sg-12345678"],
    },
)
```

## Setting Timeouts, Memory Size, and Runtime

You can also fine tune your Lambda function’s performance with adjusting its `timeout`, `memory_size`, and `runtime` environment. With `python_function`, these settings are easy to declare and adjust.

- **`timeout`**: Defines the maximum execution time for your function in seconds. The default is 3 seconds, but you can increase it for longer-running tasks.
- **`memory_size`**: Sets the amount of memory (in MB) available to the function.
- **`runtime`**: Specifies the Lambda runtime (e.g., `python3.9`). This is the default runtime, but you can set it explicitly for clarity or to ensure consistency across deployments.
- **handler**: By convention `python_function` defaults the handler code to `app.handler` this can be overridden if your handler is defined somewhere else.

### Example

```python
lambda_function = cloud_foundry.python_function(
    name="tuned-function",
    handler="app.event_handler",
    sources={"app.py": "./src/handler.py"},
    timeout=30,               # Function can run up to 30 seconds
    memory_size=256,          # Allocate 256MB RAM
    runtime="python3.9"       # Use Python 3.9 runtime
)
```

These controls help balance performance, cost, and reliability—critical for production-ready workloads.

## Recap: Less Boilerplate, More Building

With `python_function`, you:

✅ Write less YAML and more Python\
✅ Package and deploy code with dependencies easily\
✅ Configure IAM roles and VPCs declaratively\
✅ Align infrastructure with application code in a single repo

In short, it’s the missing link for modern Python developers building serverless systems with Pulumi.

Ready to simplify your Lambda deployment strategy? Try `python_function` in your next Pulumi stack and spend more time coding features—not wiring infrastructure.

---

*Got questions or success stories using ********`python_function`********? Let’s connect on ********[LinkedIn](https://www.linkedin.com)******** or leave a comment on ********[Medium](https://medium.com)********.*
