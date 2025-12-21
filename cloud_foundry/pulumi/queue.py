"""
AWS SQS Queue component for Pulumi infrastructure.

This module provides a reusable Queue component that creates an AWS SQS queue
with a dead letter queue (DLQ) and Lambda event source mapping capabilities.
The component simplifies the creation of reliable message queuing
infrastructure with built-in error handling and retry logic.

Classes:
    QueueArgs: Configuration arguments for Queue component.
    Queue: ComponentResource that creates SQS queue with DLQ.

Functions:
    queue: Factory function to create a Queue component.

Example:
    >>> from cloud_foundry.pulumi.queue import queue
    >>> my_queue = queue(
    ...     name="my-message-queue",
    ...     visibility_timeout=600,
    ...     message_retention=86400
    ... )
    >>> my_queue.subscribe(my_lambda_function)
"""

import json
from typing import Optional
from pulumi import ComponentResource, Output, ResourceOptions
import pulumi_aws as aws

from cloud_foundry.pulumi.function import Function
from cloud_foundry.utils.names import resource_id


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
    """
    A Pulumi ComponentResource that creates an AWS SQS queue with a dead
    letter queue (DLQ).

    This component sets up a main SQS queue configured with a dead letter
    queue for handling failed message processing. Messages that fail
    processing after the maximum receive count will be moved to the DLQ.

    Attributes:
        name (str): The name of the queue component.
        dlq (aws.sqs.Queue): The dead letter queue with 14-day message
            retention.
        queue (aws.sqs.Queue): The main SQS queue with configurable visibility
            timeout and message retention.
        arn (Output[str]): The ARN of the main queue.
        url (Output[str]): The URL of the main queue.

    Args:
        name (str): The name to use for the queue resources.
        args (QueueArgs): Configuration arguments for the queue including
            visibility_timeout and message_retention.
        opts (ResourceOptions, optional): Pulumi resource options.
            Defaults to None.

    Example:
        >>> queue_args = QueueArgs(
        ...     visibility_timeout=300,
        ...     message_retention=345600
        ... )
        >>> queue = Queue("my-queue", queue_args)
    """

    def __init__(self, name: str, args: QueueArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:queue:Queue", name, {}, opts)

        self.name = name
        """Create SQS queue with DLQ."""
        # Dead letter queue
        self.dlq = aws.sqs.Queue(
            f"{name}-dlq",
            name=f"{resource_id(self.name)}-dlq",
            message_retention_seconds=1209600,  # 14 days
            opts=ResourceOptions(parent=self),
        )

        # Main queue
        self.queue = aws.sqs.Queue(
            name,
            name=resource_id(self.name),
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

        # Register outputs to signal component completion
        self.register_outputs(
            {
                "arn": self.queue.arn,
                "url": self.queue.id,
                "dlq_arn": self.dlq.arn,
            }
        )

    @property
    def arn(self) -> Output[str]:
        return self.queue.arn

    @property
    def url(self) -> Output[str]:
        return self.queue.id

    def subscribe(self, function: str | Function | aws.lambda_.Function) -> None:
        """Add SQS queue as Lambda event source.

        Args:
            function: Either a function name (str), cloud_foundry Function,
                or aws.lambda_.Function instance.
        """
        # Extract function name based on type
        if isinstance(function, Function):
            function_name = function.function_name
        elif isinstance(function, aws.lambda_.Function):
            function_name = function.function_name
        else:
            function_name = function

        # Build dependencies list
        depends_on = []
        if isinstance(function, Function):
            depends_on.append(function.lambda_)
        elif isinstance(function, aws.lambda_.Function):
            depends_on.append(function)

        aws.lambda_.EventSourceMapping(
            f"{resource_id(self.name)}-source",
            event_source_arn=self.queue.arn,
            function_name=function_name,
            batch_size=10,
            opts=ResourceOptions(parent=self, depends_on=depends_on),
        )


def queue(
    name: str,
    visibility_timeout: Optional[int] = None,
    message_retention: Optional[int] = None,
    opts: ResourceOptions = None,
) -> Queue:
    """Factory function to create a Queue component.
    Args:
        name (str): The name to use for the queue resources.
        visibility_timeout (Optional[int]): Visibility timeout in seconds.
            Defaults to None (300 seconds).
        message_retention (Optional[int]): Message retention period in
            seconds. Defaults to None (345600 seconds).
        opts (ResourceOptions, optional): Pulumi resource options.
            Defaults to None.
    Returns:
        Queue: The created Queue component.
    Example:
        >>> my_queue = queue(
        ...     name="my-message-queue",
        ...     visibility_timeout=300,
        ...     message_retention=345600
        ... )
    """
    return Queue(
        name,
        QueueArgs(
            visibility_timeout=visibility_timeout, message_retention=message_retention
        ),
        opts,
    )
