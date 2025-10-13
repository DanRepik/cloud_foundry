import pulumi
import subprocess


_account_id = None


def account_id() -> str:
    global _account_id
    if not _account_id:
        _account_id = subprocess.check_output(
            [
                "aws",
                "sts",
                "get-caller-identity",
                "--query",
                "Account",
                "--output",
                "text",
            ],
            text=True,
        ).strip()

    return _account_id


_region = None


def region() -> str:
    global _region
    if not _region:
        # Get the AWS region from the AWS CLI configuration
        _region = subprocess.check_output(
            ["aws", "configure", "get", "region"], text=True
        ).strip()
    return _region


def resource_id(name: str = None, separator: str = '-') -> str:
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
