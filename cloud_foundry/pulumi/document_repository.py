import pulumi
from pulumi_aws import s3, lambda_, iam
import json

from cloud_foundry.utils.logger import logger

log = logger(__name__)


class DocumentRepository(pulumi.ComponentResource):
    def __init__(self, name, bucket_name: str = None, notifications=None, opts=None):
        super().__init__("cloud_foundry:s3:DocumentBucket", name, {}, opts)

        self.bucket_name = (
            bucket_name or f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}"
        )

        log.info(f"Creating S3 bucket: {self.bucket_name}")

        # Create an S3 bucket
        self.bucket = s3.Bucket(
            f"{name}-document-respo",
            bucket=self.bucket_name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Create lifecycle configuration separately (recommended approach)
        s3.BucketLifecycleConfigurationV2(
            f"{name}-lifecycle-config",
            bucket=self.bucket.id,
            rules=[
                s3.BucketLifecycleConfigurationV2RuleArgs(
                    id="intelligent-tiering",
                    status="Enabled",
                    transitions=[
                        s3.BucketLifecycleConfigurationV2RuleTransitionArgs(
                            days=30,
                            storage_class="INTELLIGENT_TIERING",
                        ),
                    ],
                )
            ],
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Add lambda triggers if provided
        if notifications:
            for notification in notifications:
                self.add_notification(notification)

        # Create an IAM role for the Lambda function
        assume_role_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "sts:AssumeRole",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Effect": "Allow",
                }
            ],
        }

        # Create an IAM role for the Lambda function
        self.lambda_role = iam.Role(
            f"{name}-lambda-role",
            assume_role_policy=json.dumps(assume_role_policy),
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Attach the necessary policies to the role
        iam.RolePolicyAttachment(
            f"{name}-lambda-policy-attachment",
            role=self.lambda_role.name,
            policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "bucket_name": self.bucket.bucket,
                "bucket_arn": self.bucket.arn,
                "lambda_role_arn": self.lambda_role.arn,
            }
        )

    def add_notification(self, notification: dict):
        lambda_function = notification["function"]
        prefix_filter = notification.get("prefix", "")
        suffix_filter = notification.get("suffix", "")

        # Create an S3 bucket notification
        bucket_notification = s3.BucketNotification(
            f"{self.bucket._name}-notification",
            bucket=self.bucket.id,
            lambda_functions=[
                {
                    "lambda_function_arn": lambda_function.arn,
                    "events": [
                        "s3:ObjectCreated:*",
                        "s3:ObjectRemoved:*",
                        "s3:ObjectDeleted:*",
                    ],
                    "filter_prefix": prefix_filter,
                    "filter_suffix": suffix_filter,
                }
            ],
        )

        # Grant the S3 bucket permission to invoke the Lambda function
        lambda_permission = lambda_.Permission(
            f"{lambda_function._name}-permission",
            action="lambda:InvokeFunction",
            function=lambda_function.name,
            principal="s3.amazonaws.com",
            source_arn=self.bucket.arn,
        )

        return bucket_notification, lambda_permission


def document_repository(name, bucket_name: str = None, notifications=None, opts=None):
    return DocumentRepository(name, bucket_name, notifications, opts)
