import pulumi
import pulumi_aws as aws
from typing import Union
from pulumi import ResourceOptions
from cloud_foundry.utils.logger import logger
from cloud_foundry.pulumi.rest_api import RestAPI

log = logger(__name__)


class ApiOriginArgs:
    def __init__(
        self,
        rest_api: RestAPI = None,
        name: str = None,
        domain_name=None,
        path_pattern: str = None,
        origin_path: str = None,
        origin_shield_region: str = None,
        api_key_password: str = None,
        is_target_origin: bool = False,
    ):
        self.name = name
        self.rest_api = rest_api
        self.domain_name = domain_name
        self.path_pattern = path_pattern
        self.origin_path = origin_path
        self.origin_shield_region = origin_shield_region
        self.api_key_password = api_key_password
        self.is_target_origin = is_target_origin


class ApiOrigin(pulumi.ComponentResource):
    """
    Create an API origin for CloudFront distribution.

    Args:
        name: The name of the origin, must be unique within the scope of the CloudFront instance.
        args: The API origin configuration arguments.
    """

    def __init__(self, name: str, args: ApiOriginArgs, opts: ResourceOptions = None):
        super().__init__(
            "cloud_foudry:cdn:ApiOrigin", name or args.rest_api.name, {}, opts
        )

        self.origin_id = f"{name or args.rest_api.name}-api"

        pulumi.log.debug(f"origin_id: {self.origin_id}")

        custom_headers = []
        if args.api_key_password:
            custom_headers.append({"name": "X-API-Key", "value": args.api_key_password})

        self.distribution_origin = aws.cloudfront.DistributionOriginArgs(
            domain_name=args.domain_name,
            origin_id=self.origin_id,
            origin_path=args.origin_path,
            custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                http_port=80,
                https_port=443,
                origin_protocol_policy="https-only",
                origin_ssl_protocols=["TLSv1.2"],
            ),
            custom_headers=custom_headers,
        )
        log.info(f"origin created")

        if args.origin_shield_region:
            self.distribution_origin.origin_shield = (
                aws.cloudfront.DistributionOriginOriginShieldArgs(
                    enabled=True, origin_shield_region=args.origin_shield_region
                )
            )

        self.cache_behavior = aws.cloudfront.DistributionOrderedCacheBehaviorArgs(
            path_pattern=args.path_pattern,
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
            origin_request_policy_id="59781a5b-3903-41f3-afcb-af62929ccde1",
            cache_policy_id="4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
            min_ttl=0,
            default_ttl=0,
            max_ttl=0,
            compress=True,
            viewer_protocol_policy="https-only",
        )

        self.register_outputs(
            {"origin": self.distribution_origin, "cache_behavior": self.cache_behavior}
        )
