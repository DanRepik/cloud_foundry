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
        whitelist_countries: Optional[List[str]] = None,
    ):
        self.sites = sites
        self.apis = apis
        self.hosted_zone_id = hosted_zone_id
        self.site_domain_name = site_domain_name
        self.comment = comment
        self.root_uri = root_uri
        self.whitelist_countries = whitelist_countries


class CDN(pulumi.ComponentResource):
    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:CDN", name, {}, opts)

        if not args.sites and not args.apis:
            raise ValueError("At least one site or api should be present")

        hosted_zone_id = args.hosted_zone_id or self.find_hosted_zone_id(name)
        domain_name = f"{pulumi.get_stack()}.{args.site_domain_name}"

        # Request a certificate for the domain and its subdomains
        certificate = aws.acm.Certificate(
            f"{name}-cert",
            domain_name=domain_name,
            validation_method="DNS",
            subject_alternative_names=[f"*.{domain_name}"],
            opts=ResourceOptions(parent=self),
        )

        # Create DNS validation records
        pulumi.Output.all(certificate.domain_validation_options).apply(
            lambda domain_validation_options: [
                aws.route53.Record(
                    f"{validation_option['domain_name']}-validation",
                    name=validation_option["resource_record_name"],
                    type=validation_option["resource_record_type"],
                    zone_id=hosted_zone_id,
                    records=[validation_option["resource_record_value"]],
                    ttl=60,
                    opts=ResourceOptions(parent=self),
                )
                for domain_validation_option in domain_validation_options
                for validation_option in domain_validation_option
            ]
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
            aliases=[domain_name] if args.site_domain_name else None,
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
                    locations=args.whitelist_countries
                    or [
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
                acm_certificate_arn=certificate.arn,
                ssl_support_method="sni-only",
                minimum_protocol_version="TLSv1.2_2021",
            ),
            origins=origins,
            opts=ResourceOptions(parent=self, depends_on=[certificate]),
        )

        if hosted_zone_id:
            log.info(f"hosted_zone_id: {hosted_zone_id}")
            self.dns_alias = aws.route53.Record(
                f"{name}-alias",
                name=domain_name,
                type="A",
                zone_id=hosted_zone_id,
                aliases=[
                    aws.route53.RecordAliasArgs(
                        name=self.distribution.domain_name,
                        zone_id=self.distribution.hosted_zone_id.apply(lambda id: id),
                        evaluate_target_health=True,
                    )
                ],
                opts=ResourceOptions(parent=self, depends_on=[self.distribution]),
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
                    target_origin_id = site_args.origin_id

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
            f"{name}-log",
            bucket=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-cf-log",
            force_destroy=True,  # This ensures the bucket is deleted even if it contains objects
            opts=ResourceOptions(parent=self),
        )

        ownership_controls = aws.s3.BucketOwnershipControls(
            "example",
            bucket=log_bucket.id,
            rule={
                "object_ownership": "BucketOwnerPreferred",
            },
            opts=ResourceOptions(parent=self),
        )

        # Grant CloudFront write permissions to the bucket.
        aws.s3.get_canonical_user_id_output
        aws.s3.BucketAclV2(
            f"{name}-log-bucket_acl",
            bucket=log_bucket.id,
            access_control_policy={
                "grants": [
                    {
                        "grantee": {
                            "type": "CanonicalUser",
                            "id": aws.cloudfront.get_log_delivery_canonical_user_id().id,
                        },
                        "permission": "WRITE",
                    }
                ],
                "owner": {"id": aws.s3.get_canonical_user_id().id},
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[ownership_controls]),
        )

        """

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
                                "Principal": {"Service": "cloudfront.amazonaws.com"},
                                "Action": ["s3:PutObject", "s3:GetBucketAcl"],
                                "Resource": f"{arn}/logs/*",
                            }
                        ],
                    }
                )
            ),
            opts=ResourceOptions(parent=self),
        )

        """
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
