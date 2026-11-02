"""Subscribe an SQS queue to an SNS topic, optionally with a filter policy.

Works with a topic this program creates (``Topic.subscribe`` delegates here)
and with one imported by ARN from another stack, which is the common case
when a consumer stack listens to a producer's event topic.

Example:
    >>> from cloud_foundry import queue, subscribe_queue_to_topic
    >>> inbox = queue("index-requests", visibility_timeout=900)
    >>> subscribe_queue_to_topic(
    ...     "index-requests-events",
    ...     topic_arn=foundation.get_output("ingestion_events_topic_arn"),
    ...     queue=inbox,
    ...     filter_policy={"operation": ["artifact_version_created"]},
    ...     filter_policy_scope="MessageBody",
    ... )
"""

import json
from typing import Any, Optional, Union

import pulumi_aws as aws
from pulumi import Input, Output, ResourceOptions

from cloud_foundry.utils.names import resource_id

FilterPolicy = Union[dict[str, Any], Output]


def _policy_json(filter_policy: Optional[FilterPolicy]):
    if filter_policy is None:
        return None
    return Output.from_input(filter_policy).apply(
        lambda policy: json.dumps(policy, sort_keys=True)
    )


def subscribe_queue_to_topic(
    name: str,
    *,
    topic_arn: Input[str],
    queue,
    filter_policy: Optional[FilterPolicy] = None,
    filter_policy_scope: Optional[str] = None,
    raw_message_delivery: bool = False,
    opts: Optional[ResourceOptions] = None,
) -> aws.sns.TopicSubscription:
    """Allow the topic to send to the queue, and subscribe the queue.

    Args:
        name: Logical name; the queue policy and subscription are named
            ``<resource_id(name)>-policy`` and ``<resource_id(name)>-sub``.
        topic_arn: ARN of the topic, created here or imported.
        queue: A cloud_foundry ``Queue`` (anything exposing ``.arn`` and
            ``.url``).
        filter_policy: SNS filter policy, as a dict. ``None`` delivers
            every message.
        filter_policy_scope: ``"MessageAttributes"`` (SNS's default) or
            ``"MessageBody"`` to filter on top-level fields of a JSON body.
        raw_message_delivery: Deliver the published message as is, without
            the SNS envelope.
        opts: Pulumi options applied to both resources.

    Note:
        The queue policy created here is the queue's only policy. A queue
        subscribed to two topics this way would have each policy overwrite
        the other; give each topic its own queue.
    """
    resource_opts = opts or ResourceOptions()
    rid = resource_id(name)

    queue_policy = aws.sqs.QueuePolicy(
        f"{rid}-policy",
        queue_url=queue.url,
        policy=Output.all(queue_arn=queue.arn, topic_arn=topic_arn).apply(
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

    subscription_args: dict[str, Any] = {
        "topic": topic_arn,
        "protocol": "sqs",
        "endpoint": queue.arn,
    }
    policy_json = _policy_json(filter_policy)
    if policy_json is not None:
        subscription_args["filter_policy"] = policy_json
        if filter_policy_scope:
            subscription_args["filter_policy_scope"] = filter_policy_scope
    if raw_message_delivery:
        subscription_args["raw_message_delivery"] = True

    return aws.sns.TopicSubscription(
        f"{rid}-sub",
        **subscription_args,
        opts=ResourceOptions.merge(
            resource_opts, ResourceOptions(depends_on=[queue_policy])
        ),
    )
