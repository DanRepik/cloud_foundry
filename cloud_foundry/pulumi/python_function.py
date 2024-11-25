# python_function.py

import pulumi
import pulumi_aws as aws
from cloud_foundry.utils.logger import logger

from cloud_foundry.python_archive_builder import PythonArchiveBuilder
from cloud_foundry.pulumi.function import Function

log = logger(__name__)

def python_function(
    name: str, *,
    handler: str = None,
    memory_size: int = None,
    timeout: int = None,
    sources: dict[str, str] = [],
    requirements: list[str] = [],
    policy_statements: list[str] = [],
    environment: dict[str, str] = [],
    vpc_config: dict= None
) -> Function:
    archive_builder = PythonArchiveBuilder(
        name=f"{name}-archive-builder",
        sources=sources,
        requirements=requirements,
        working_dir="temp",
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
        vpc_config=vpc_config
    )
