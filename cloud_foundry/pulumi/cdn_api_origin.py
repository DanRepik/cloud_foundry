import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions


class ApiOriginArgs:
    def __init__(
        self,
        domain_name: str,
        path_pattern: str,
        origin_path: str = "",
        origin_shield_region: str = None,
        api_key_password: str = None,
    ):
        self.domain_name = domain_name
        self.path_pattern = path_pattern
        self.origin_path = origin_path
        self.origin_shield_region = origin_shield_region
        self.api_key_password = api_key_password


class ApiOrigin(pulumi.ComponentResource):
    """
    Create an API origin for CloudFront distribution.

    Args:
        name: The name of the origin, must be unique within the scope of the CloudFront instance.
        args: The API origin configuration arguments.
    """

    def __init__(self, name: str, args: ApiOriginArgs, opts: ResourceOptions = None):
        super().__init__("custom:resource:ApiOrigin", name, {}, opts)

        self.origin_id = f"{name}-api"

        pulumi.log.debug(f"origin_id: {self.origin_id}")

        custom_headers = []
        if args.api_key_password:
            custom_headers.append({"name": "X-API-Key", "value": args.api_key_password})

        self.origin = aws.cloudfront.DistributionOriginArgs(
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

        if args.origin_shield_region:
            self.origin.origin_shield = (
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
            forwarded_values=aws.cloudfront.DistributionOrderedCacheBehaviorForwardedValuesArgs(
                query_string=True,
                headers=[
                    "Authorization",
                    "Sec-WebSocket-Key",
                    "Sec-WebSocket-Version",
                    "Sec-WebSocket-Protocol",
                    "Sec-WebSocket-Accept",
                    "Sec-WebSocket-Extensions",
                    "Accept-Encoding",
                ],
                cookies=aws.cloudfront.DistributionOrderedCacheBehaviorForwardedValuesCookiesArgs(
                    forward="none"
                ),
            ),
            min_ttl=0,
            default_ttl=0,
            max_ttl=0,
            compress=True,
            viewer_protocol_policy="https-only",
        )

        self.register_outputs(
            {"origin": self.origin, "cache_behavior": self.cache_behavior}
        )
