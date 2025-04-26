from pulumi import ComponentResource, ResourceOptions, Output
import pulumi_aws as aws
from importlib import resources
import json
import subprocess
from cloud_foundry.utils.names import resource_id
from cloud_foundry.pulumi.python_function import python_function


class MailPublisher(ComponentResource):
    def __init__(
        self, name, mail_identity: str, mail_origin: str, templates: str, opts=None
    ):
        super().__init__("cloud_foundry:services:MailSender", name, {}, opts)

        account_id = subprocess.check_output(
            [
                "aws",
                "sts",
                "get-caller-identity",
                "--query",
                "Account",
                "--output",
                "text",
            ],
            text=True,
        ).strip()
        region = subprocess.check_output(
            ["aws", "configure", "get", "region"], text=True
        ).strip()

        # Create an SNS Topic
        self.topic = aws.sns.Topic(
            f"{name}-topic",
            name=f"{resource_id(name)}-topic",
            opts=ResourceOptions(parent=self),
        )

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
                        f"arn:aws:ses:{region}:{account_id}:identity/{mail_identity}"
                    ],
                }
            ],
            environment={"MAIL_ORIGIN": mail_origin},
        )

        # Subscribe the Lambda Function to the SNS Topic
        aws.sns.TopicSubscription(
            f"{name}-subscription",
            topic=self.topic.arn,
            protocol="lambda",
            endpoint=publisher_function.arn,
            opts=ResourceOptions(parent=self),
        )

        # Create an SNS Topic Policy
        aws.sns.TopicPolicy(
            f"{name}-sns-publish-policy",
            arn=self.topic.arn,
            policy=Output.all(self.topic.arn, region, account_id).apply(
                lambda args: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": "ses.amazonaws.com"  # Allow SES to publish
                                },
                                "Action": "sns:Publish",
                                "Resource": args[0],  # Topic ARN
                                "Condition": {
                                    "StringEquals": {
                                        "AWS:SourceArn": f"arn:aws:ses:{args[1]}:{args[2]}:identity/{mail_identity}"
                                    }
                                },
                            }
                        ],
                    }
                )
            ),
            opts=ResourceOptions(parent=self),
        )

        aws.sns.TopicSubscription(
            f"{name}-email-subscription",
            topic=self.topic,
            protocol="lambda",
            endpoint=publisher_function.arn,
            opts=ResourceOptions(depends_on=[publisher_function], parent=self),
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
