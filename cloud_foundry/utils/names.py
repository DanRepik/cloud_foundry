import os

import pulumi
import pulumi_aws as aws


_account_id = None


def account_id() -> str:
    global _account_id
    if not _account_id:
        _account_id = aws.get_caller_identity().account_id

    return _account_id


_region = None


def region() -> str:
    global _region
    if not _region:
        _region = aws.get_region().name
    return _region


def project_slug() -> str:
    """
    Resolve the short name to use as the "project" component of generated
    AWS resource names.

    AWS resource names are frequently length-limited (SNS topics, IAM
    roles, Lambda functions, DynamoDB tables, ...), so a Pulumi project
    with a long `name:` in Pulumi.yaml can push `resource_id()`-generated
    names past those limits, forcing names to be overridden by hand at
    each call site.

    Projects can opt into a shorter alias two ways, checked in this
    order:

    1. The `CLOUD_FOUNDRY_PROJECT_SLUG` environment variable, e.g.:

           export CLOUD_FOUNDRY_PROJECT_SLUG=cep

       Useful for CI or a local shell override without touching checked-in
       stack config.

    2. The `project_slug` Pulumi config value, e.g.:

           pulumi config set civarai-evidence:project_slug cep

    If neither is set, falls back to the full Pulumi project name
    (`pulumi.get_project()`) — existing behavior is unchanged unless a
    project explicitly opts in.

    Returns:
        str: The configured project slug, or the full Pulumi project name
            if no slug has been configured.
    """
    env_slug = (os.environ.get("CLOUD_FOUNDRY_PROJECT_SLUG") or "").strip()
    if env_slug:
        return env_slug

    config_slug = (pulumi.Config().get("project_slug") or "").strip()
    return config_slug or pulumi.get_project()


def resource_id(name: str = None, separator: str = "-") -> str:
    """
    Generate a standardized resource ID by combining the project slug, stack
    name, and resource name.

    The project component is `project_slug()` rather than the raw Pulumi
    project name, so a project can configure a short alias (e.g. "cep"),
    via the `CLOUD_FOUNDRY_PROJECT_SLUG` environment variable or the
    `project_slug` Pulumi config value, to keep generated AWS names under
    service length limits.

    Args:
        name (str): The base name of the resource.

    Returns:
        str: A standardized resource ID in the format "project-stack-resource".
    """
    project = project_slug()
    stack = pulumi.get_stack()
    return f"{project}{separator}{stack}{separator + name if name else ''}"
