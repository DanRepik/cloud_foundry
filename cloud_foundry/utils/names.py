import pulumi


def resource_id(name: str) -> str:
    """
    Generate a standardized resource ID by combining the project name, stack name, and resource name.

    Args:
        name (str): The base name of the resource.

    Returns:
        str: A standardized resource ID in the format "project-stack-resource".
    """
    project = pulumi.get_project()
    stack = pulumi.get_stack()
    return f"{project}-{stack}-{name}"
