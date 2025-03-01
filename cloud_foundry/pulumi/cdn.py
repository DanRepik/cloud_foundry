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
        create_apex: Optional[bool] = False,
        hosted_zone_id: Optional[str] = None,
        site_domain_name: Optional[str] = None,
        root_uri: Optional[str] = None,
        whitelist_countries: Optional[List[str]] = None,
    ):
        self.sites = sites
        self.apis = apis
        self.create_apex = create_apex
        self.hosted_zone_id = hosted_zone_id
        self.site_domain_name = site_domain_name
        self.root_uri = root_uri
        self.whitelist_countries = whitelist_countries


class CDN(pulumi.ComponentResource):
    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:CDN", name, {}, opts)

        if not args.sites and not args.apis:
            raise ValueError("At least one site or api should be present")

        self.hosted_zone_id = args.hosted_zone_id or self.find_hosted_zone_id(name)
        self.domain_name = f"{pulumi.get_stack()}.{args.site_domain_name}"

        subject_alternative_names = [self.domain_name] if args.create_apex else []

        origins, caches, target_origin_id = self.get_origins(name, args)
        log_bucket = self.set_up_log_bucket(name)
        certificate = self.set_up_certificate(name)

        log.info("starting distribution")
        self.distribution = aws.cloudfront.Distribution(
            f"{name}-distro",
            comment=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}",
            enabled=True,
            is_ipv6_enabled=True,
#            comment=args.comment,
            default_root_object=args.root_uri,
            logging_config=aws.cloudfront.DistributionLoggingConfigArgs(
                bucket=log_bucket.bucket_domain_name,
                include_cookies=False,
                prefix="logs/",
            ),
            aliases=[self.domain_name] if args.site_domain_name else None,
            default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
                target_origin_id=target_origin_id,
                viewer_protocol_policy="redirect-to-https",
                allowed_methods=["GET", "HEAD", "OPTIONS"],
                cached_methods=["GET", "HEAD"],
                forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
                    query_string=True,
                    cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                        forward="all")
                ),
                compress=True,
                default_ttl=86400,
                max_ttl=31536000,
                min_ttl=1,
                response_headers_policy_id=aws.cloudfront.get_response_headers_policy(
                    name="Managed-SimpleCORS",
                ).id,
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
            viewer_certificate={
                "acm_certificate_arn":certificate.arn,
                "ssl_support_method":"sni-only",
                "minimum_protocol_version": "TLSv1.2_2021",
            },
            origins=origins,
            opts=ResourceOptions(
                parent=self, depends_on=[certificate, log_bucket], custom_timeouts={"delete": "30m"}
            ),
        )
        for site in self.site_origins:
            site.create_policy(self.distribution.id)

        if self.hosted_zone_id:
            log.info(f"hosted_zone_id: {self.hosted_zone_id}")
            self.dns_alias = aws.route53.Record(
                f"{name}-alias",
                name=self.domain_name,
                type="A",
                zone_id=self.hosted_zone_id,
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
        self.site_origins = []

        if args.sites:
            for site_args in args.sites:
                site = SiteOrigin(f"{name}-{site_args.name}", site_args)
                origins.append(site.distribution_origin)
                self.site_origins.append(site)
                if site_args.is_target_origin:
                    target_origin_id = site_args.origin_id

        if args.apis:
            for api in args.apis:
                origin = aws.cloudfront.DistributionOriginArgs(
                    domain_name=api.domain_name,
                    origin_id=api.origin_id,
                    custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                        http_port=80,
                        https_port=443,
                        origin_protocol_policy="https-only",
                        origin_ssl_protocols=["TLSv1.2"],
                    ),
                )
                origins.append(origin)
                cache_behavior = aws.cloudfront.DistributionOrderedCacheBehaviorArgs(
                    path_pattern=api.path_pattern,
                    allowed_methods=["GET", "HEAD", "OPTIONS"],
                    cached_methods=["GET", "HEAD"],
                    target_origin_id=api.origin_id,
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

        log.info(f"target_origin_id: {target_origin_id}")
        log.info(f"origins: {origins}")
        log.info(f"caches: {caches}") 
        return origins, caches, target_origin_id
    
    def set_up_log_bucket(self, name: str):
        log_bucket = aws.s3.Bucket(
            f"{name}-log",
            bucket=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-cf-log",
            force_destroy=True,  # This ensures the bucket is deleted even if it contains objects
            opts=ResourceOptions(parent=self),
        )

        ownership_controls = aws.s3.BucketOwnershipControls(
            f"{name}-log-bucket-ownership-controls",
            bucket=log_bucket.id,
            rule={
                "object_ownership": "BucketOwnerPreferred",
            },
            opts=ResourceOptions(parent=self),
        )

        # Grant CloudFront write permissions to the bucket.
        aws.s3.BucketAclV2(
            f"{name}-log-bucket_acl",
            bucket=log_bucket.id,
            acl="log-delivery-write",
            opts=pulumi.ResourceOptions(parent=self, depends_on=[ownership_controls]),
        )

        return log_bucket
    
    def set_up_certificate(self, name):
        certificate = aws.acm.Certificate(f"{name}-certificate", 
            domain_name = self.domain_name,
            validation_method = "DNS",
            opts=ResourceOptions(parent=self),
        )

        # Retrieve the DNS validation options
        validationOptions = certificate.domain_validation_options.apply(lambda options: options[0])

        # Create a Route 53 DNS record for validation
        dnsRecord = aws.route53.Record(f"{name}-validation-record", 
            name= validationOptions.resource_record_name,
            zone_id= self.hosted_zone_id, 
            type= validationOptions.resource_record_type,
            records= [validationOptions.resource_record_value],
            ttl= 60,
            opts=ResourceOptions(parent=self),
        )

        # Validate the ACM certificate
        certificateValidation = aws.acm.CertificateValidation(f"{name}-certificate-validation", 
            certificate_arn= certificate.arn,
            validation_record_fqdns= [dnsRecord.fqdn],
            opts=ResourceOptions(parent=self),
        )

        return certificate


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
