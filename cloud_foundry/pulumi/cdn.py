import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from typing import List, Optional
import json

from cloud_foundry.pulumi.cdn_api_origin import ApiOrigin, ApiOriginArgs
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
        certificate, validation = self.set_up_certificate(name, self.domain_name)

        log.info("starting distribution")
        self.distribution = aws.cloudfront.Distribution(
            f"{name}-distro",
            comment=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}",
            enabled=True,
            is_ipv6_enabled=True,
            default_root_object=args.root_uri,
#            logging_config=aws.cloudfront.DistributionLoggingConfigArgs(
#                bucket=log_bucket.bucket_domain_name,
#                include_cookies=False,
#                prefix="logs/",
#            ),
            aliases=[self.domain_name] if args.site_domain_name else None,
            default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
                target_origin_id=target_origin_id,
                viewer_protocol_policy="redirect-to-https",
                allowed_methods=["GET", "HEAD", "OPTIONS"],
                cached_methods=["GET", "HEAD"],
                forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
                    query_string=True,
                    cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                        forward="all"
                    ),
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
                "acm_certificate_arn": certificate.arn,
                "ssl_support_method": "sni-only",
                "minimum_protocol_version": "TLSv1.2_2021",
            },
            origins=origins,
            opts=ResourceOptions(
                parent=self,
                depends_on=[certificate, validation, log_bucket],
                custom_timeouts={"delete": "30m"},
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
            for api_args in args.apis:
                if self.hosted_zone_id and api_args.rest_api:
                    api_args.domain_name = self.setup_custom_domain(
                        name=api_args.name,
                        hosted_zone_id=self.hosted_zone_id,
                        domain_name=f"{api_args.name}-{self.domain_name}",
                        stage_name=api_args.rest_api.name,
                        rest_api_id=api_args.rest_api.rest_api_id,
                    )
                api_origin = ApiOrigin(f"{name}-{api_args.name}", api_args)
                origins.append(api_origin.distribution_origin)
                caches.append(api_origin.cache_behavior)
                if api_args.is_target_origin:
                    target_origin_id = api_args.origin_id

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
            force_destroy=True,  
            opts=ResourceOptions(parent=self),
        )

        # Grant CloudFront write permissions to the bucket.
        aws.s3.BucketPolicy(
            f"{name}-log-bucket-policy",
            bucket=log_bucket.id,
            policy=log_bucket.id.apply(
                lambda bucket_id: json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudfront.amazonaws.com"},
                            "Action": "s3:PutObject",
                            "Resource": f"arn:aws:s3:::{bucket_id}/*",
                            "Condition": {
                                "StringEquals": {
                                    "AWS:SourceArn": f"arn:aws:cloudfront::{aws.get_caller_identity().account_id}:distribution/*"
                                }
                            }
                        }
                    ]
                })
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        return log_bucket

    def set_up_certificate(self, name, domain_name):
        certificate = aws.acm.Certificate(
            f"{name}-certificate",
            domain_name=domain_name,
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
        )

        # Retrieve the DNS validation options
        validationOptions = certificate.domain_validation_options.apply(
            lambda options: options[0]
        )

        # Create a Route 53 DNS record for validation
        dnsRecord = aws.route53.Record(
            f"{name}-validation-record",
            name=validationOptions.resource_record_name,
            zone_id=self.hosted_zone_id,
            type=validationOptions.resource_record_type,
            records=[validationOptions.resource_record_value],
            ttl=60,
            opts=ResourceOptions(parent=self),
        )

        # Validate the ACM certificate
        validation = aws.acm.CertificateValidation(
            f"{name}-certificate-validation",
            certificate_arn=certificate.arn,
            validation_record_fqdns=[dnsRecord.fqdn],
            opts=ResourceOptions(parent=self),
        )

        return certificate, validation

    def setup_custom_domain(
        self,
        name: str,
        hosted_zone_id: str,
        domain_name: str,
        stage_name: str,
        rest_api_id,
    ):
        certificate, validation = self.set_up_certificate(name, domain_name)

        custom_domain = aws.apigateway.DomainName(
            f"{name}-custom-domain",
            domain_name=domain_name,
            regional_certificate_arn=certificate.arn,
            endpoint_configuration={
                "types": "REGIONAL",
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[validation]),
        )

        # Define the base path mapping
        base_path_mapping = aws.apigateway.BasePathMapping(
            f"{name}-base-path-map",
            rest_api=rest_api_id,
            stage_name=stage_name,
            domain_name=custom_domain.domain_name,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[custom_domain]),
        )

        # Define the DNS record
        dns_record = aws.route53.Record(
            f"{name}-dns-record",
            name=custom_domain.domain_name,
            type="A",
            zone_id=hosted_zone_id,
            aliases=[
            {
                "name": custom_domain.regional_domain_name,
                "zone_id": custom_domain.regional_zone_id,
                "evaluate_target_health": False,
            }
            ],
            opts=pulumi.ResourceOptions(parent=self, depends_on=[custom_domain]),
        )

        return domain_name

    def find_hosted_zone_id(self, name: str) -> str:
        # Implement your logic to find the hosted zone ID
        pass


def cdn(
    name: str,
    sites: list[dict],
    apis: list[dict],
    hosted_zone_id: Optional[str] = None,
    site_domain_name: Optional[str] = None,
    root_uri: Optional[str] = None,
    opts: ResourceOptions = None,
) -> CDN:
    site_origins = []
    for site in sites:
        log.info(f"site: {site}")
        site_origins.append(SiteOriginArgs(**site))
    api_origins = []
    for api in apis:
        log.info(f"api: {api}")
        api_origins.append(ApiOriginArgs(**api))
    log.info(f"site_origins: {site_origins}")
    log.info(f"api_origins: {api_origins}")
    return CDN(
        name,
        CDNArgs(
            sites=site_origins,
            apis=api_origins,
            hosted_zone_id=hosted_zone_id,
            site_domain_name=site_domain_name,
            root_uri=root_uri,
        ),
        opts,
    )
