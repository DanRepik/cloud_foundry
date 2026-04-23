# python_function.py

from typing import Optional, Union
import pulumi
from cloud_foundry.utils.logger import logger

from cloud_foundry.python_archive_builder import PythonArchiveBuilder
from cloud_foundry.pulumi.function import (
    Function,
    PolicyStatementsInput,
    default_lambda_architecture,
)

log = logger(__name__)


def python_function(
    name: str,
    *,
    handler: str = None,
    memory_size: Optional[int] = None,
    timeout: Optional[int] = None,
    sources: dict[str, str] = None,
    requirements: Optional[list[str]] = None,
    policy_statements: Optional[PolicyStatementsInput] = None,
    environment: Optional[dict[str, Union[str, pulumi.Output[str]]]] = None,
    vpc_config: Optional[dict] = None,
    runtime: Optional[str] = None,
    architecture: Optional[str] = None,
    opts=None,
) -> Function:
    resolved_architecture = architecture or default_lambda_architecture()
    archive_builder = PythonArchiveBuilder(
        name=f"{name}-archive-builder",
        sources=sources,
        requirements=requirements,
        working_dir="temp",
        target_architecture=resolved_architecture,
    )
    return Function(
        name=name,
        hash=archive_builder.hash(),
        memory_size=memory_size,
        timeout=timeout,
        handler=handler,
        archive_location=archive_builder.location(),
        environment=environment,
        policy_statements=policy_statements,
        vpc_config=vpc_config,
        runtime=runtime,
        architectures=[resolved_architecture],
        opts=opts,
    )
