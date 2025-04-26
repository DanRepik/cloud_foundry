import os
import subprocess
import cloud_foundry
import pulumi

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
    sources={"app.py": "mail_publisher.py", "templates": "templates"},
    requirements=["jinja2"],
    policy_statements=[
        {
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
