"""
Wiring for the shared idle-ESM-reaper Lambda (owned by
civarai-evidence/infra/shared-foundation). Queue owners call
`attach_idle_reaper` after subscribing their Lambda to their queue so the
reaper auto-disables the event source mapping once the queue is fully
drained -- avoiding empty-poll SQS request volume from a mapping nobody
remembered to turn off.

Re-enabling is still each producer's own responsibility -- the reaper never
does it on its own initiative -- but `attach_idle_reaper` now also wires an
on-demand path for that: a second EventRule, scoped to this consumer's
queue, that matches a custom "EnableMapping" event and re-enables the
mapping unconditionally (no drain/depth check needed for that direction).
Producers trigger it via `cloud_foundry.utils.idle_reaper_client.
request_mapping_enable(queue_url)` -- see that module's docstring for the
tradeoff between importing it from `cloud_foundry` (pulls in pulumi/
pulumi-aws transitively, same as any other cloud_foundry import) versus
inlining its few lines directly in a dependency-sensitive Lambda. Producers
only ever need the queue URL they already have to know to call SendMessage
in the first place; they never need the event source mapping's UUID or the
reaper's function/role names.

The reaper's function name and IAM role name are computed deterministically
via cloud_foundry's own naming convention (see
cloud_foundry.utils.names.resource_id) rather than read from
shared-foundation's stack outputs, so no cross-repo Pulumi state dependency
is introduced. Callers pass those names in explicitly (see
infra/shared-foundation/__main__.py for the exact formula).
"""

import json
from typing import Optional

import pulumi_aws as aws
from pulumi import Output, ResourceOptions

from cloud_foundry.utils.names import account_id, region


def _aws_name(prefix: str, suffix: str, max_length: int) -> str:
    """Build a physical AWS resource name, truncating `prefix` (never
    `suffix`) so the result fits `max_length`. Resource-type-specific AWS
    name limits (e.g. EventRule.name and EventTarget.target_id are both
    capped at 64 chars) are easy to overflow once `prefix` incorporates a
    project + stack + queue name, so every resource below sets its physical
    name explicitly through this rather than relying on Pulumi's default
    autonaming (logical name + random suffix), which has the same overflow
    risk plus non-determinism.
    """
    name = f"{prefix}-{suffix}"
    if len(name) <= max_length:
        return name
    return f"{prefix[: max_length - len(suffix) - 1]}-{suffix}"


def attach_idle_reaper(
    queue,
    event_source_mapping: aws.lambda_.EventSourceMapping,
    *,
    reaper_function_name: str,
    reaper_role_name: str,
    resource_prefix: str,
    interval_minutes: int = 10,
    event_bus_name: str = "default",
    opts: Optional[ResourceOptions] = None,
) -> None:
    """Schedule the shared idle-esm-reaper Lambda against one queue/mapping,
    and wire an on-demand re-enable path for the same mapping.

    Args:
        queue: The cloud_foundry Queue (or anything exposing `.arn`/`.url`)
            whose event source mapping should be auto-disabled once idle.
        event_source_mapping: The aws.lambda_.EventSourceMapping returned by
            `queue.subscribe(...)`.
        reaper_function_name: Deployed function name of the shared reaper
            Lambda (see infra/shared-foundation).
        reaper_role_name: Name of the reaper Lambda's execution role, used to
            attach a scoped inline policy granting access to just this
            queue/mapping.
        resource_prefix: Unique prefix for this consumer's Pulumi resource
            names, e.g. `resource_id("workflow")`.
        interval_minutes: How often the reaper checks this queue.
        event_bus_name: EventBridge bus the on-demand enable rule listens
            on. Must match the bus `idle_reaper_client.request_mapping_enable`
            callers publish to -- both default to the account's "default"
            bus, so this only needs to change if a consumer already uses a
            dedicated custom bus.
        opts: Pulumi ResourceOptions (e.g. `parent=`) applied to every
            resource created here.
    """
    esm_arn = event_source_mapping.id.apply(
        lambda uuid: f"arn:aws:lambda:{region()}:{account_id()}:event-source-mapping:{uuid}"
    )

    aws.iam.RolePolicy(
        f"{resource_prefix}-idle-reaper-policy",
        name=_aws_name(resource_prefix, "idle-reaper-policy", 128),
        role=reaper_role_name,
        policy=Output.all(queue.arn, esm_arn).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["sqs:GetQueueAttributes"],
                            "Resource": args[0],
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "lambda:GetEventSourceMapping",
                                "lambda:UpdateEventSourceMapping",
                            ],
                            "Resource": args[1],
                        },
                    ],
                }
            )
        ),
        opts=opts,
    )

    rule = aws.cloudwatch.EventRule(
        f"{resource_prefix}-idle-reaper-schedule",
        name=_aws_name(resource_prefix, "idle-reaper-schedule", 64),
        schedule_expression=f"rate({interval_minutes} minutes)",
        opts=opts,
    )

    reaper_arn = (
        f"arn:aws:lambda:{region()}:{account_id()}:function:{reaper_function_name}"
    )

    aws.cloudwatch.EventTarget(
        f"{resource_prefix}-idle-reaper-target",
        target_id=_aws_name(resource_prefix, "idle-reaper-target", 64),
        rule=rule.name,
        arn=reaper_arn,
        input=Output.all(queue.url, event_source_mapping.id).apply(
            lambda args: json.dumps(
                {
                    "queue_url": args[0],
                    "queue_name": resource_prefix,
                    "event_source_mapping_uuid": args[1],
                }
            )
        ),
        opts=opts,
    )

    aws.lambda_.Permission(
        f"{resource_prefix}-idle-reaper-invoke",
        statement_id=_aws_name(resource_prefix, "idle-reaper-invoke", 100),
        action="lambda:InvokeFunction",
        function=reaper_function_name,
        principal="events.amazonaws.com",
        source_arn=rule.arn,
        opts=opts,
    )

    # On-demand enable path. Scoped to this consumer's own queue URL, so a
    # request_mapping_enable() call from any producer only ever wakes the
    # one EventRule whose queue_url it matches -- unmatched events are
    # dropped by EventBridge, no coordination needed across consumers.
    enable_rule = aws.cloudwatch.EventRule(
        f"{resource_prefix}-idle-reaper-enable",
        name=_aws_name(resource_prefix, "idle-reaper-enable", 64),
        event_bus_name=event_bus_name,
        event_pattern=queue.url.apply(
            lambda queue_url: json.dumps(
                {
                    "source": ["cloud_foundry.idle_reaper"],
                    "detail-type": ["EnableMapping"],
                    "detail": {"queue_url": [queue_url]},
                }
            )
        ),
        opts=opts,
    )

    aws.cloudwatch.EventTarget(
        f"{resource_prefix}-idle-reaper-enable-target",
        target_id=_aws_name(resource_prefix, "idle-reaper-enable-tgt", 64),
        rule=enable_rule.name,
        event_bus_name=event_bus_name,
        arn=reaper_arn,
        input=event_source_mapping.id.apply(
            lambda uuid: json.dumps(
                {
                    "action": "enable",
                    "queue_name": resource_prefix,
                    "event_source_mapping_uuid": uuid,
                }
            )
        ),
        opts=opts,
    )

    aws.lambda_.Permission(
        f"{resource_prefix}-idle-reaper-enable-invoke",
        statement_id=_aws_name(resource_prefix, "idle-reaper-enable-invoke", 100),
        action="lambda:InvokeFunction",
        function=reaper_function_name,
        principal="events.amazonaws.com",
        source_arn=enable_rule.arn,
        opts=opts,
    )
