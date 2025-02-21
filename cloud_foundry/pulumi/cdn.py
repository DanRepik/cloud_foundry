import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from typing import List, Optional
import json

from cloud_foundry.pulumi.cdn_api_origin import ApiOriginArgs
from cloud_foundry.pulumi.cdn_site_origin import SiteOrigin, SiteOriginArgs
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class CDNArgs:
    def __init__(
        self,
        sites: Optional[List[dict]] = None,
        apis: Optional[List[dict]] = None,
        hosted_zone_id: Optional[str] = None,
        site_domain_name: Optional[str] = None,
        comment: Optional[str] = None,
        root_uri: Optional[str] = None,
    ):
        self.sites = sites
        self.apis = apis
        self.hosted_zone_id = hosted_zone_id
        self.site_domain_name = site_domain_name
        self.comment = comment
        self.root_uri = root_uri


class CDN(pulumi.ComponentResource):
    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry::CDN", name, {}, opts)

        if not args.sites and not args.apis:
            raise ValueError("At least one site or api should be present")

        hosted_zone_id = args.hosted_zone_id or self.find_hosted_zone_id(name)

        site_certificate = aws.acm.Certificate(
            f"{name}-cert",
            domain_name=args.site_domain_name or f"{name}.{hosted_zone_id}",
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
        )

        origins, caches, target_origin_id = self.get_origins(name, args)

        self.distribution = aws.cloudfront.Distribution(
            f"{name}-distro",
            enabled=True,
            is_ipv6_enabled=True,
            comment=args.comment,
            default_root_object=args.root_uri,
            logging_config=aws.cloudfront.DistributionLoggingConfigArgs(
                bucket=self.set_up_log_bucket(name).bucket_domain_name,
                include_cookies=False,
                prefix="logs/",
            ),
            aliases=[f"{name}.{hosted_zone_id}"] if hosted_zone_id else None,
            default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
                allowed_methods=["GET", "HEAD", "OPTIONS"],
                cached_methods=["GET", "HEAD"],
                target_origin_id=target_origin_id,
                forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
                    query_string=False,
                    headers=[],
                    cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                        forward="none"
                    ),
                ),
                compress=True,
                viewer_protocol_policy="redirect-to-https",
                min_ttl=1,
                default_ttl=86400,
                max_ttl=31536000,
            ),
            ordered_cache_behaviors=caches,
            price_class="PriceClass_100",
            restrictions=aws.cloudfront.DistributionRestrictionsArgs(
                geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
                    restriction_type="whitelist",
                    locations=[
                        "US",
                        "CA",
                        "GB",
                        "IE",
                        "MT",
                        "FR",
                        "BR",
                        "BG",
                        "ES",
                        "CH",
                        "AE",
                        "DE",
                    ],
                )
            ),
            viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
                acm_certificate_arn=site_certificate.arn,
                ssl_support_method="sni-only",
                minimum_protocol_version="TLSv1.2_2021",
            ),
            origins=origins,
            opts=ResourceOptions(parent=self),
        )

        if hosted_zone_id:
            self.dns_alias = aws.route53.Record(
                f"{name}-alias",
                name=f"{name}.{hosted_zone_id}",
                type="A",
                zone_id=hosted_zone_id,
                aliases=[
                    aws.route53.RecordAliasArgs(
                        name=self.distribution.domain_name,
                        zone_id=self.distribution.hosted_zone_id,
                        evaluate_target_health=True,
                    )
                ],
                opts=ResourceOptions(parent=self),
            )
            self.domain_name = self.dns_alias.name
        else:
            self.domain_name = self.distribution.domain_name

    def get_origins(self, name: str, args: CDNArgs):
        target_origin_id = None
        origins = []
        caches = []

        if args.sites:
            for site_args in args.sites:
                site = SiteOrigin(f"{name}-{site_args.name}", site_args)
                origins.append(site.distribution_origin)
                if site_args.is_target_origin:
                    target_origin_id = site["origin_id"]

        if args.apis:
            for api in args.apis:
                origin = aws.cloudfront.DistributionOriginArgs(
                    domain_name=api["domain_name"],
                    origin_id=api["origin_id"],
                    custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                        http_port=80,
                        https_port=443,
                        origin_protocol_policy="https-only",
                        origin_ssl_protocols=["TLSv1.2"],
                    ),
                )
                origins.append(origin)
                cache_behavior = aws.cloudfront.DistributionOrderedCacheBehaviorArgs(
                    path_pattern=api["path_pattern"],
                    allowed_methods=["GET", "HEAD", "OPTIONS"],
                    cached_methods=["GET", "HEAD"],
                    target_origin_id=api["origin_id"],
                    forwarded_values=aws.cloudfront.DistributionOrderedCacheBehaviorForwardedValuesArgs(
                        query_string=True,
                        headers=["Authorization"],
                        cookies=aws.cloudfront.DistributionOrderedCacheBehaviorForwardedValuesCookiesArgs(
                            forward="all"
                        ),
                    ),
                    compress=True,
                    viewer_protocol_policy="redirect-to-https",
                    min_ttl=0,
                    default_ttl=3600,
                    max_ttl=86400,
                )
                caches.append(cache_behavior)
                if api.get("is_target_origin"):
                    target_origin_id = api["origin_id"]

        if target_origin_id is None:
            target_origin_id = origins[0].origin_id

        return origins, caches, target_origin_id

    def set_up_log_bucket(self, name: str):
        log_bucket = aws.s3.Bucket(
            f"{name}-cf-log", acl="private", opts=ResourceOptions(parent=self)
        )

        aws.s3.BucketPolicy(
            f"{name}-log-bucket-policy",
            bucket=log_bucket.id,
            policy=log_bucket.arn.apply(
                lambda arn: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "delivery.logs.amazonaws.com"},
                                "Action": "s3:PutObject",
                                "Resource": f"{arn}/logs/*",
                            }
                        ],
                    }
                )
            ),
            opts=ResourceOptions(parent=self),
        )

        return log_bucket

    def find_hosted_zone_id(self, name: str) -> str:
        # Implement your logic to find the hosted zone ID
        pass


def cdn(
    name: str,
    sites: list[dict],
    apis: list[dict],
    hosted_zone_id: Optional[str] = None,
    site_domain_name: Optional[str] = None,
    comment: Optional[str] = None,
    root_uri: Optional[str] = None,
    opts: ResourceOptions = None,
) -> CDN:
    site_origins = []
    for site in sites:
        log.info(f"site: {site}")
        site_origins.append(SiteOriginArgs(**site))
    api_origins = []
    for api in apis:
        api_origins.append(ApiOriginArgs(**api))
    return CDN(
        name,
        CDNArgs(
            sites=site_origins,
            apis=api_origins,
            hosted_zone_id=hosted_zone_id,
            site_domain_name=site_domain_name,
            comment=comment,
            root_uri=root_uri,
        ),
        opts,
    )
