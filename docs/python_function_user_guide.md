# Streamlining AWS Lambda Deployment with `python_function`

When deploying cloud-native applications, managing Lambda functions often becomes a tangle of zipping files, configuring permissions, and handling packaging nuances. The `python_function` utility comes from Cloud Foundry, which is curated toolkit of components built to simplify cloud-centric application development. Think of it as a modular collection of building blocks—each one purpose-built to help build cloud centric applications faster. With `python_function`, what used to be a mess of manual steps becomes a clean, declarative experience.

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

The result? A deployable Lambda with source code, environment config, and deployment orchestration—all automated using Cloud Foundry.

## Developer-Friendly Source Packaging

The `sources` argument is a dictionary that maps destination paths in the deployment package to their corresponding source file paths or directories. This provides precise control over which files or folders are included in your Lambda function and where they are placed. One of its standout features is the flexibility in the types of resources you can include. Source resources can be:

- **Single files**: Map a single file to a specific destination in the deployment package. `{ "app.py": "app.py" }`
- **Directories**: Include entire folders and their contents. `{ "handlers": "handlers" }`
- **Inline code**: Embed Python code directly as a string. `{ "app.py": """def handler(...): ...""" }`

This versatility ensures that your deployment package is tailored to your application's needs, whether you're working with standalone scripts, structured directories, or dynamically generated code.

This makes it easy to integrate into any CI/CD pipeline without needing additional packaging tools.

## Including Python Dependencies

In addition to source code, your Lambda function may depend on external Python packages. You can specify these using the `requirements` parameter, just like a `requirements.txt` file:

```python
requirements=[
    "requests"
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

Need access to a database inside a VPC? Just declare your the VPC config:

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
    handler="my_handler.event_handler",
    sources={"my_handler.py": "./src/my_handler.py"},
    timeout=30,               # Function can run up to 30 seconds
    memory_size=256,          # Allocate 256MB RAM
    runtime="python3.9"       # Use Python 3.9 runtime
)
```

These controls help balance performance, cost, and reliability—critical for production-ready workloads.

## Python Function in Action

While the `Hello World` example provides a foundational understanding of building Lambda services, this section will showcase how to leverage `python_function` to create a practical, real-world service. By exploring a more comprehensive implementation, you'll see how `python_function` simplifies the deployment of production-ready serverless applications.

## Building an Email Publisher Service

In this section, we’ll create an email publisher service using `python_function`. This service will asynchronously send emails by receiving notifications from AWS SNS Topics or SQS queues. Allowing customer based services to be more responsive since they are not waiting on emails be assembled and sent.

Complete source code can be found on GitHub at; https://github.com/DanRepik/cloud_foundry/tree/main/examples/mail_publisher


### Service Overview

The email publisher service will:

1. Process the incoming messages to extract email details (e.g., recipient, subject, body).
2. Generate the email body using a predefined template.
3. Send emails using an external email service provider (e.g., Amazon SES or a third-party API).

### Project Structure

Here’s the project structure for the mail publisher service example:

```
examples/
└── mail-publisher/
    ├── __main__.py
    ├── mail_publisher.py
    ├── Pulumi.yaml
    ├── requirements.txt
    └── templates/
        └── hello.html
```

- **`mail_publisher.py`**: Contains the Lambda function code for processing messages and sending emails.
- **`requirements.txt`**: Lists the Python dependencies required to deploy the function using Pulumi.
- **`__main__.py`**: Here is where the python_function is defined.
- **`templates`**: This is the folder that contains the templates available.


### Understanding `__main__.py`

The `__main__.py` file serves as the entry point for defining and deploying the `mail_publisher` service. It uses the `python_function` utility to map the `mail_publisher.py` file as the Lambda function's handler and includes the `templates` folder as part of the deployment package.

Here’s how the `__main__.py` file ties everything together:

```python
import os
import subprocess
import cloud_foundry
import pulumi

# variables needed from the environment
account_id = subprocess.check_output(
    ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
    text=True,
).strip()
region = subprocess.check_output(
    ["aws", "configure", "get", "region"], text=True
).strip()
mail_identity = os.environ["MAIL_IDENTITY"]
mail_origin = os.environ["MAIL_ORIGIN"]


# Create the Lambda Function
publisher_function = cloud_foundry.python_function(
    "mail-publisher",
    sources={
        # include the service code
        "app.py": "mail_publisher.py",
        # include the templates
        "templates": "templates"},
    requirements=["jinja2"],
    policy_statements=[
        {
            # sets up permission to send emails
            "Effect": "Allow",
            "Actions": ["ses:SendEmail"],
            "Resources": [
                f"arn:aws:ses:{region}:{account_id}:identity/{mail_identity}"
            ],
        }
    ],
    environment={"MAIL_ORIGIN": mail_origin},
)

pulumi.export("function_name", publisher_function.function_name)
```

### Lambda Service Code

The following code defines the AWS Lambda function for an email publisher service that processes messages from SNS Topics or SQS queues to send emails using Amazon SES. It extracts email details (recipients, subject, template name, etc.), renders the email body using Jinja2 templates, and sends emails via SES.

```python
import boto3
import json
from jinja2 import Template
import os
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

ses_client = boto3.client("ses")

MAIL_ORIGIN = os.environ["MAIL_ORIGIN"]


def handler(event, context):
    log.info("Received event: %s", json.dumps(event))
    try:
        responses = []
        for record in event["Records"]:
            if "Sns" in record:
                sns_message = json.loads(record["Sns"]["Message"])
            elif "body" in record:
                sns_message = json.loads(record["body"])
            else:
                raise ValueError("Unsupported message format")

            template_name = sns_message["template_name"]
            context_data = sns_message["context"]
            recipients = sns_message["recipients"]
            subject = sns_message["subject"]
            cc = sns_message.get("cc", [])
            bcc = sns_message.get("bcc", [])

            email_body = render_template(template_name, context_data)
            response = send_email(recipients, subject, email_body, cc, bcc)
            responses.append(response)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Emails sent successfully", "responses": responses}
            ),
        }

    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def render_template(template_name, context):
    log.info(f"Loading template: {template_name}")
    template_path = os.path.join(os.path.dirname(__file__), "templates", template_name)
    with open(template_path, "r") as file:
        template_content = file.read()

    template = Template(template_content)
    return template.render(context)


def send_email(recipients, subject, body, cc, bcc):
    response = ses_client.send_email(
        Source=MAIL_ORIGIN,  # Use the email from the environment variable
        Destination={
            "ToAddresses": recipients,
            "CcAddresses": cc,  # Add CC addresses
            "BccAddresses": bcc,  # Add BCC addresses
        },
        Message={"Subject": {"Data": subject}, "Body": {"Html": {"Data": body}}},
    )
    return response
```

## Setting up the Templates

To include email templates with the Lambda function, create a `templates` folder and add your templates there. For example, add a `hello.html` file to the folder. Since the `templates` folder is included in the Lambda function's sources, the templates will be accessible during execution.

### Example `hello.html` Template

The `hello.html` file can contain the following HTML code:

```html
<!DOCTYPE html>
<html>
<head>
    <title>{{ subject }}</title>
</head>
<body>
    <h1>Hello, {{ name }}!</h1>
    <p>We sent you an email.</p>
    <p>Best regards,</p>
    <p>The Team</p>
</body>
</html>
```

### Deploy the Function

Now with the service code and templates in place we can proceed to deploy the function by running;

```bash
pulumi up -y
```

### Deployment and Testing

Once the function is deployed, you can test it by invoking it programmatically using the `boto3` library. Below is an example script that demonstrates how to trigger the Lambda function and pass the required payload:

```python
#!/usr/bin/env python3

import boto3
import json
import os

recepient_email = os.environ["RECIPIENT_EMAIL"]
publisher_function = os.environ["PUBLISHER_FUNCTION"]

# Initialize the Lambda client
lambda_client = boto3.client("lambda")

# Invoke the Lambda function
response = lambda_client.invoke(
    FunctionName=publisher_function,  # Replace with your Lambda function name
    InvocationType="RequestResponse",  # Use 'Event' for asynchronous invocation
    Payload=json.dumps({
        "Records": [
            {
                "Sns": {
                    "Message": json.dumps(
                        {
                            "template_name": "hello.html",
                            "recipients": [recepient_email],
                            "subject": "Test Email",
                            "context": {"name": "John Doe"},
                        }
                    )
                }
            }
        ]
    }),
)

# Print the response
response_payload = json.loads(response["Payload"].read())
print("Response:", response_payload)
```

This script sends a test payload to the deployed Lambda function, verifying its behavior and ensuring proper input processing.

By leveraging `python_function`, you can effortlessly create a robust, serverless email publisher service that enables seamless asynchronous communication between application components.

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
