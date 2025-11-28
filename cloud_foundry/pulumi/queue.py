import json
from typing import Optional
from pulumi import ComponentResource, Output, ResourceOptions
import pulumi_aws as aws


class QueueArgs:
    """Arguments for Queue component."""

    def __init__(
        self,
        visibility_timeout: Optional[int] = None,
        message_retention: Optional[int] = None,
    ) -> None:
        self.visibility_timeout = visibility_timeout or 300  # 5 minutes
        self.message_retention = message_retention or 345600  # 4 days


class Queue(ComponentResource):
    def __init__(self, name: str, args: QueueArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:queue:Queue", name, {}, opts)

        self.name = name
        """Create SQS queue with DLQ."""
        # Dead letter queue
        self.dlq = aws.sqs.Queue(
            f"{name}-dlq",
            name=f"{name}-dlq",
            message_retention_seconds=1209600,  # 14 days
            opts=ResourceOptions(parent=self),
        )

        # Main queue
        self.queue = aws.sqs.Queue(
            name,
            name=name,
            visibility_timeout_seconds=args.visibility_timeout,
            message_retention_seconds=args.message_retention,
            redrive_policy=self.dlq.arn.apply(
                lambda arn: json.dumps(
                    {
                        "deadLetterTargetArn": arn,
                        "maxReceiveCount": 3,
                    }
                )
            ),
            opts=ResourceOptions(parent=self),
        )

    @property
    def arn(self) -> Output[str]:
        return self.queue.arn

    @property
    def url(self) -> Output[str]:
        return self.queue.id


def queue(
    name: str,
    visibility_timeout: Optional[int] = None,
    message_retention: Optional[int] = None,
    opts: ResourceOptions = None,
) -> Queue:
    return Queue(
        name,
        QueueArgs(
            visibility_timeout=visibility_timeout, message_retention=message_retention
        ),
        opts,
    )
