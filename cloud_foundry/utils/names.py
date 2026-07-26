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


def resource_id(name: str = None, separator: str = "-") -> str:
    """
    Generate a standardized resource ID by combining the project name, stack name,
    and resource name.

    Args:
        name (str): The base name of the resource.

    Returns:
        str: A standardized resource ID in the format "project-stack-resource".
    """
    project = pulumi.get_project()
    stack = pulumi.get_stack()
    return f"{project}{separator}{stack}{separator + name if name else ''}"
