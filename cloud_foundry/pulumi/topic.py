"""SNS Topic component for Pub/Sub messaging."""

import json
from typing import Optional
from pulumi import ComponentResource, Output, ResourceOptions
import pulumi_aws as aws
from cloud_foundry.utils.names import resource_id
from .queue import Queue


class TopicArgs:
    """Arguments for Topic component."""

    def __init__(
        self, display_name: Optional[str], subscriptions: Optional[list[dict]] = None
    ):
        self.display_name = display_name
        self.subscriptions = subscriptions


class Topic(ComponentResource):
    """
    A Pulumi ComponentResource that creates an AWS SNS Topic with optional
    subscriptions.
    This component sets up an SNS Topic and allows for optional subscriptions
    to SQS queues.
    Attributes:
        name (str): The name of the topic component.
        topic (aws.sns.Topic): The SNS Topic resource.
    Args:
        name (str): The name to use for the topic resource.
        args (TopicArgs): Configuration arguments for the topic including
            display_name and subscriptions.
        opts (ResourceOptions, optional): Pulumi resource options.
            Defaults to None.
    Example:
        >>> topic_args = TopicArgs(
        ...     display_name="My Topic",
        ...     subscriptions=[{"queue": my_queue}])
        >>> topic = Topic("my-topic", topic_args)
    """

    def __init__(self, name: str, args: TopicArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:topic:Topic", name, {}, opts)

        self.name = name
        self.topic = aws.sns.Topic(
            name,
            name=resource_id(name),
            display_name=args.display_name or name,
            opts=ResourceOptions(parent=self),
        )

        if args.subscriptions:
            for subscription in args.subscriptions:
                if subscription.get("queue"):
                    self.subscribe(subscription["queue"])

        # Register outputs to signal component completion
        self.register_outputs(
            {
                "arn": self.topic.arn,
                "name": self.topic.name,
            }
        )

    @property
    def arn(self) -> Output[str]:
        """Get the ARN of the SNS topic."""
        return self.topic.arn

    def subscribe(self, queue: Queue, opts: ResourceOptions = None) -> None:
        """Subscribe an SQS queue to this SNS topic.
        Args:
            queue (Queue): The SQS queue to subscribe.
            opts (ResourceOptions, optional): Pulumi resource options.
        """
        name = f"{self.name}-{queue.name}"

        # Merge parent options with provided options
        resource_opts = ResourceOptions.merge(ResourceOptions(parent=self), opts)

        # Allow SNS to send messages to SQS
        queue_policy = aws.sqs.QueuePolicy(
            f"{resource_id(name)}-policy",
            queue_url=queue.url,
            policy=Output.all(queue_arn=queue.arn, topic_arn=self.topic.arn).apply(
                lambda args: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "sns.amazonaws.com"},
                                "Action": "sqs:SendMessage",
                                "Resource": args["queue_arn"],
                                "Condition": {
                                    "ArnEquals": {"aws:SourceArn": args["topic_arn"]}
                                },
                            }
                        ],
                    }
                )
            ),
            opts=resource_opts,
        )

        # Subscribe queue to topic (depends on policy being created first)
        aws.sns.TopicSubscription(
            f"{resource_id(name)}-sub",
            topic=self.topic.arn,
            protocol="sqs",
            endpoint=queue.arn,
            opts=ResourceOptions.merge(
                resource_opts, ResourceOptions(depends_on=[queue_policy])
            ),
        )


def topic(
    name: str,
    display_name: Optional[str] = None,
    subscriptions: Optional[list[dict]] = None,
    opts: ResourceOptions = None,
) -> Topic:
    """Factory function to create a Topic component.
    Args:
        name (str): The name to use for the topic resource.
        display_name (Optional[str]): The display name for the SNS topic.
            Defaults to None.
        subscriptions (Optional[list[dict]]): List of subscription configs.
            Each config should be a dict with a 'queue' key for SQS queues.
            Defaults to None.
        opts (ResourceOptions, optional): Pulumi resource options.
            Defaults to None.
    Returns:
        Topic: The created Topic component.
    Example:
        >>> my_topic = topic(
        ...     name="my-topic",
        ...     display_name="My Topic",
        ...     subscriptions=[{"queue": my_queue}]
        ... )
    """
    return Topic(
        name, TopicArgs(display_name=display_name, subscriptions=subscriptions), opts
    )
