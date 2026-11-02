"""Run a Lambda function on a schedule (EventBridge rule, target, permission).

Example:
    >>> from cloud_foundry import python_function, schedule
    >>> worker = python_function("index-worker", sources={...})
    >>> schedule(
    ...     "index-reconcile",
    ...     schedule_expression="rate(1 hour)",
    ...     function=worker,
    ...     input={"operation": "index_reconcile"},
    ... )
"""

import json
from typing import Any, Optional, Union

import pulumi_aws as aws
from pulumi import ComponentResource, Input, Output, ResourceOptions

from cloud_foundry.pulumi.function import Function
from cloud_foundry.utils.names import resource_id


def _function_name(function) -> Input[str]:
    # Outputs of the Lambda resource, not Function.function_name (a plain
    # string), so the permission waits for the function to exist.
    if isinstance(function, Function):
        return function.lambda_.name
    if isinstance(function, aws.lambda_.Function):
        return function.name
    return function


def _function_arn(function) -> Input[str]:
    if isinstance(function, Function):
        return function.lambda_.arn
    if isinstance(function, aws.lambda_.Function):
        return function.arn
    raise TypeError(
        "schedule() needs a cloud_foundry Function or aws.lambda_.Function; "
        "pass target_arn for any other target"
    )


class Schedule(ComponentResource):
    """An EventBridge rule on a schedule with one target.

    Targets a Lambda function (the invoke permission is created here), or any
    other EventBridge target by ``target_arn`` (the caller grants EventBridge
    whatever that target needs, and may pass ``role_arn``).

    Attributes:
        rule (aws.cloudwatch.EventRule): The scheduled rule.
        target (aws.cloudwatch.EventTarget): Its single target.
    """

    def __init__(
        self,
        name: str,
        *,
        schedule_expression: str,
        function: Union[Function, aws.lambda_.Function, None] = None,
        target_arn: Optional[Input[str]] = None,
        role_arn: Optional[Input[str]] = None,
        input: Optional[Union[dict[str, Any], Output]] = None,
        enabled: bool = True,
        description: Optional[str] = None,
        opts: Optional[ResourceOptions] = None,
    ):
        super().__init__("cloud_foundry:schedule:Schedule", name, {}, opts)
        if (function is None) == (target_arn is None):
            raise ValueError("schedule() takes exactly one of function or target_arn")

        rid = resource_id(name)
        child = ResourceOptions(parent=self)

        # EventRule names are limited to 64 characters.
        self.rule = aws.cloudwatch.EventRule(
            f"{name}-rule",
            name=rid[:64],
            schedule_expression=schedule_expression,
            state="ENABLED" if enabled else "DISABLED",
            description=description,
            opts=child,
        )

        target_args: dict[str, Any] = {
            "rule": self.rule.name,
            "target_id": rid[:64],
            "arn": _function_arn(function) if function is not None else target_arn,
        }
        if input is not None:
            target_args["input"] = Output.from_input(input).apply(json.dumps)
        if role_arn is not None:
            target_args["role_arn"] = role_arn
        self.target = aws.cloudwatch.EventTarget(
            f"{name}-target", **target_args, opts=child
        )

        if function is not None:
            aws.lambda_.Permission(
                f"{name}-invoke",
                statement_id=f"{rid}-schedule"[:100],
                action="lambda:InvokeFunction",
                function=_function_name(function),
                principal="events.amazonaws.com",
                source_arn=self.rule.arn,
                opts=child,
            )

        self.register_outputs({"rule_arn": self.rule.arn})

    @property
    def rule_arn(self) -> Output[str]:
        return self.rule.arn


def schedule(
    name: str,
    *,
    schedule_expression: str,
    function: Union[Function, aws.lambda_.Function, None] = None,
    target_arn: Optional[Input[str]] = None,
    role_arn: Optional[Input[str]] = None,
    input: Optional[Union[dict[str, Any], Output]] = None,
    enabled: bool = True,
    description: Optional[str] = None,
    opts: Optional[ResourceOptions] = None,
) -> Schedule:
    """Create a Schedule component.

    Args:
        name: Logical name; the rule is named ``resource_id(name)``.
        schedule_expression: ``rate(...)`` or ``cron(...)``.
        function: A Lambda function to invoke. Exactly one of ``function``
            and ``target_arn``.
        target_arn: Any other EventBridge target.
        role_arn: Role EventBridge assumes for ``target_arn`` targets that
            need one.
        input: JSON-serializable event sent to the target.
        enabled: Create the rule disabled when False.
        description: Rule description.
        opts: Pulumi resource options.
    """
    return Schedule(
        name,
        schedule_expression=schedule_expression,
        function=function,
        target_arn=target_arn,
        role_arn=role_arn,
        input=input,
        enabled=enabled,
        description=description,
        opts=opts,
    )
