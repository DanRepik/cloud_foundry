import json
from typing import Optional
from pulumi import ComponentResource, Output, ResourceOptions
import pulumi_aws as aws
from cloud_foundry.utils.names import resource_id
from .queue import Queue


class TopicArgs:
    """Arguments for Topic component."""

    def __init__(self, display_name: str, subscriptions: Optional[list[dict]] = None):
        self.display_name = display_name
        self.subscriptions = subscriptions


class Topic(ComponentResource):
    def __init__(self, name: str, args: TopicArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:topic:Topic", name, {}, opts)

        self.name = name
        """Create SNS topic."""
        self.topic = aws.sns.Topic(
            resource_id(name),
            name=name,
            display_name=args.display_name,
            opts=ResourceOptions(parent=self),
        )

        if args.subscriptions:
            for subscription in args.subscriptions:
                if subscription.get("queue"):
                    self.subscribe_queue(subscription["queue"])

    def subscribe_queue(self, queue: Queue) -> None:
        """Subscribe SQS queue to SNS topic."""
        name = f"{self.name}={queue.name}"
        # Allow SNS to send messages to SQS
        aws.sqs.QueuePolicy(
            f"{resource_id()}-policy",
            queue_url=queue.url,
            policy=Output.all(queue.arn, self.topic.arn).apply(
                lambda args: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "sns.amazonaws.com"},
                                "Action": "sqs:SendMessage",
                                "Resource": args[0],
                                "Condition": {"ArnEquals": {"aws:SourceArn": args[1]}},
                            }
                        ],
                    }
                )
            ),
            opts=ResourceOptions(parent=self),
        )

        # Subscribe queue to topic
        aws.sns.TopicSubscription(
            f"{resource_id(name)}-sub",
            topic=self.topic.arn,
            protocol="sqs",
            endpoint=queue.arn,
            opts=ResourceOptions(parent=self),
        )


def topic(name: str, display_name: str, opts: ResourceOptions = None) -> Topic:
    return Topic(name, TopicArgs(display_name=display_name), opts)
