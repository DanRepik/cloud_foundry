# localstack.py
import json
import os
import pulumi
from cloud_foundry import logger

log = logger(__name__)

def is_localstack_deployment() -> bool:
    """
    Determines if the Pulumi stack is being deployed to LocalStack by checking
    both environment variables and Pulumi stack configuration (aws:endpoints).

    Returns:
        bool: True if LocalStack deployment is detected, False otherwise.
    """
    # Check for LocalStack-related environment variables
    localstack_vars = ['LOCALSTACK_HOSTNAME', 'LOCALSTACK_URL', 'AWS_ENDPOINT_URL']
    for var in localstack_vars:
        if os.getenv(var):
            return True

    # Check Pulumi stack configuration for custom AWS service endpoints
    config = pulumi.Config("aws")
    endpoints_str = config.get('endpoints')
    if not endpoints_str:
        return False

    # Parse the endpoints as a list of dictionaries
    endpoints = json.loads(endpoints_str)
    # Iterate through the list of dictionaries
    for endpoint in endpoints:
        for service, url in endpoint.items():
            if 'localhost' in url:
                return True

    # Default to False if neither environment variables nor config indicate LocalStack
    return False
