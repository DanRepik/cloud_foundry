"""SNS Topic component for Pub/Sub messaging."""

from typing import Optional
from pulumi import ComponentResource, Output, ResourceOptions
import pulumi_aws as aws
from cloud_foundry.utils.names import resource_id
from .queue import Queue
from .topic_subscription import subscribe_queue_to_topic


class TopicArgs:
    """Arguments for Topic component."""

    def __init__(
        self,
        display_name: Optional[str],
        subscriptions: Optional[list[dict]] = None,
        tags: Optional[dict[str, str]] = None,
    ):
        self.display_name = display_name
        self.subscriptions = subscriptions
        self.tags = tags or {}


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
        topic_name = resource_id(name)
        self.topic = aws.sns.Topic(
            name,
            name=topic_name,
            display_name=args.display_name or name,
            tags={"Name": topic_name, **args.tags},
            opts=ResourceOptions(parent=self),
        )

        if args.subscriptions:
            for subscription in args.subscriptions:
                if subscription.get("queue"):
                    self.subscribe(
                        subscription["queue"],
                        filter_policy=subscription.get("filter_policy"),
                        filter_policy_scope=subscription.get("filter_policy_scope"),
                        raw_message_delivery=subscription.get(
                            "raw_message_delivery", False
                        ),
                    )

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

    @property
    def topic_name(self) -> Output[str]:
        """Get the deployed AWS name of the SNS topic.

        Named `topic_name` rather than `name` because `self.name` already
        holds the logical component name (a plain str, used internally for
        default display_name and subscription resource naming) -- reusing
        `name` for this would shadow that with an Output[str] and break it.
        """
        return self.topic.name

    def subscribe(
        self,
        queue: Queue,
        opts: ResourceOptions = None,
        filter_policy: Optional[dict] = None,
        filter_policy_scope: Optional[str] = None,
        raw_message_delivery: bool = False,
    ) -> None:
        """Subscribe an SQS queue to this SNS topic.
        Args:
            queue (Queue): The SQS queue to subscribe.
            opts (ResourceOptions, optional): Pulumi resource options.
            filter_policy (dict, optional): SNS filter policy. None delivers
                every message.
            filter_policy_scope (str, optional): "MessageAttributes" (the
                SNS default) or "MessageBody".
            raw_message_delivery (bool): Deliver without the SNS envelope.
        """
        subscribe_queue_to_topic(
            f"{self.name}-{queue.name}",
            topic_arn=self.topic.arn,
            queue=queue,
            filter_policy=filter_policy,
            filter_policy_scope=filter_policy_scope,
            raw_message_delivery=raw_message_delivery,
            # Parented to the topic, as before, so existing stacks keep
            # their resource URNs.
            opts=ResourceOptions.merge(ResourceOptions(parent=self), opts),
        )


def topic(
    name: str,
    display_name: Optional[str] = None,
    subscriptions: Optional[list[dict]] = None,
    tags: Optional[dict[str, str]] = None,
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
        tags (Optional[dict[str, str]]): Extra tags applied to the topic,
            alongside the "Name" tag it already gets set to its own
            resource_id()-generated name. A "Name" key here overrides
            that default.
        opts (ResourceOptions, optional): Pulumi resource options.
            Defaults to None.
    Returns:
        Topic: The created Topic component.
    Example:
        >>> my_topic = topic(
        ...     name="my-topic",
        ...     display_name="My Topic",
        ...     subscriptions=[{"queue": my_queue}],
        ...     tags={"Environment": "prod"},
        ... )
    """
    return Topic(
        name,
        TopicArgs(display_name=display_name, subscriptions=subscriptions, tags=tags),
        opts,
    )
