import pulumi
import pulumi_aws as aws
from typing import Optional
from pulumi import ResourceOptions
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class ApiOriginArgs:
    def __init__(
        self,
        name: str = None,
        domain_name: str = None,
        path_pattern: str = None,
        origin_path: str = None,
        origin_shield_region: str = None,
        api_key_password: str = None,
        is_target_origin: bool = False,
    ):
        self.name = name
        self.domain_name = domain_name
        self.path_pattern = path_pattern
        self.origin_path = origin_path
        self.origin_shield_region = origin_shield_region
        self.api_key_password = api_key_password
        self.is_target_origin = is_target_origin


class ApiOrigin(pulumi.ComponentResource):
    """
    Create an API origin for a CloudFront distribution.

    Args:
        name: The name of the origin, must be unique within the scope of
            the CloudFront instance.
        args: The API origin configuration arguments.
    """

    def __init__(
        self,
        name: str,
        *,
        domain_name: str,
        origin_path: Optional[str] = None,
        path_pattern: str,
        shield_region: Optional[str] = None,
        api_key_password: Optional[str] = None,
        opts: ResourceOptions = None,
    ):
        super().__init__("cloud_foundry:cdn:ApiOrigin", name, {}, opts)

        self.origin_id = f"{name}-api"
        log.info(f"Creating API origin with ID: {self.origin_id}")
        log.info(f"Domain name type: {type(domain_name)}, value: {domain_name}")

        # Configure custom headers if API key is provided
        custom_headers = []
        if api_key_password:
            custom_headers.append({"name": "X-API-Key", "value": api_key_password})
            log.debug("Custom headers configured for API key.")

        # If domain_name is an Output, we need to handle it properly
        # Pulumi should handle Output automatically, but let's ensure it's properly typed
        if isinstance(domain_name, pulumi.Output):
            log.info(
                "Domain name is a Pulumi Output - will be resolved at deployment time"
            )

        # Define the CloudFront distribution origin
        self.distribution_origin = aws.cloudfront.DistributionOriginArgs(
            domain_name=domain_name,
            origin_id=self.origin_id,
            origin_path=origin_path,
            custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                http_port=80,
                https_port=443,
                origin_protocol_policy="https-only",
                origin_ssl_protocols=["TLSv1.2"],
            ),
            custom_headers=custom_headers,
        )

        # Define a custom origin request policy
        aws.cloudfront.OriginRequestPolicy(
            f"{name}-request-policy",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-request-policy",
            cookies_config={
                "cookie_behavior": "none",  # Do not forward cookies
            },
            headers_config={
                "header_behavior": "whitelist",  # Forward only specific headers
                "headers": {
                    "items": ["Origin"],  # Add headers your origin needs
                },
            },
            query_strings_config={
                "query_string_behavior": "all",  # Forward all query strings
            },
        )
        log.info(f"Custom origin request policy created for: {name}")

        # Configure Origin Shield if specified
        if shield_region:
            self.distribution_origin.origin_shield = (
                aws.cloudfront.DistributionOriginOriginShieldArgs(
                    enabled=True, origin_shield_region=shield_region
                )
            )
            log.info(f"Origin Shield enabled for region: {shield_region}")

        # Define the cache behavior for the origin
        self.cache_behavior = aws.cloudfront.DistributionOrderedCacheBehaviorArgs(
            path_pattern=path_pattern,
            allowed_methods=[
                "DELETE",
                "GET",
                "HEAD",
                "OPTIONS",
                "PATCH",
                "POST",
                "PUT",
            ],
            cached_methods=["GET", "HEAD"],
            target_origin_id=self.origin_id,
            origin_request_policy_id=aws.cloudfront.get_origin_request_policy(
                name="Managed-AllViewerExceptHostHeader"
            ).id,
            cache_policy_id=aws.cloudfront.get_cache_policy(
                name="Managed-CachingDisabled"
            ).id,
            min_ttl=0,
            default_ttl=0,
            max_ttl=0,
            compress=True,
            viewer_protocol_policy="https-only",
        )
        log.info(f"Cache behavior configured for path pattern: {path_pattern}")

        # Register outputs
        self.register_outputs(
            {"origin": self.distribution_origin, "cache_behavior": self.cache_behavior}
        )
        log.info(f"API origin setup completed for: {self.origin_id}")
