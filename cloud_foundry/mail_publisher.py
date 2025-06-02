from pulumi import ComponentResource, ResourceOptions, Output
import pulumi_aws as aws
from importlib import resources
import json
from cloud_foundry.utils.names import resource_id
from cloud_foundry.pulumi.python_function import python_function
from cloud_foundry.pulumi.publisher import publisher
from cloud_foundry.utils.names import account_id, region


class MailPublisher(ComponentResource):
    def __init__(
        self, name, mail_identity: str, mail_origin: str, templates: str, opts=None
    ):
        super().__init__("cloud_foundry:services:MailSender", name, {}, opts)

        with resources.open_text("cloud_foundry", "services/mail_publisher.py") as file:
            mail_sender_code = file.read()

        function_name = f"{resource_id(name)}-lambda"
        print(f"mail_identity: {mail_identity}")
        # Create the Lambda Function
        publisher_function = python_function(
            f"{name}-lambda",
            sources={"app.py": mail_sender_code, "templates": templates},
            requirements=["jinja2"],
            policy_statements=[
                {
                    "Effect": "Allow",
                    "Actions": ["ses:SendEmail"],
                    "Resources": [
                        f"arn:aws:ses:{region()}:{account_id()}:identity/{mail_identity}"
                    ],
                }
            ],
            environment={"MAIL_ORIGIN": mail_origin},
        )

        self.mail_publisher = publisher(
            "mail-publisher",
            subscriptions=[
                {
                    "function": f"{name}-lambda",
                    "filter": {
                        "event_type": ["email"],
                        "email_type": ["welcome"],
                    },
                }
            ],
        )

        self.register_outputs(
            {
                "topic_arn": self.topic.arn,
                "lambda_function_name": publisher_function.name,
            }
        )


def mail_publisher(
    name, mail_identity: str, mail_origin: str, templates: str, opts=None
):
    return MailPublisher(
        name,
        mail_identity=mail_identity,
        mail_origin=mail_origin,
        templates=templates,
        opts=opts,
    )
