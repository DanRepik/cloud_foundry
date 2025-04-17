import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from typing import List, Optional

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
        error_responses: Optional[list] = None,
        root_uri: Optional[str] = None,
        whitelist_countries: Optional[List[str]] = None,
    ):
        self.sites = sites
        self.apis = apis
        self.create_apex = create_apex
        self.hosted_zone_id = hosted_zone_id
        self.site_domain_name = site_domain_name
        self.error_responses = error_responses
        self.root_uri = root_uri
        self.whitelist_countries = whitelist_countries


class CDN(pulumi.ComponentResource):
    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:CDN", name, {}, opts)

        if not args.sites and not args.apis:
            raise ValueError("At least one site or API should be present")

        self.hosted_zone_id = args.hosted_zone_id or self.find_hosted_zone_id(name)
        self.domain_name = f"{pulumi.get_stack()}.{args.site_domain_name}"

        origins, caches, target_origin_id = self.get_origins(name, args)
        certificate, validation = self.set_up_certificate(
            name,
            self.domain_name,
            [args.site_domain_name] if args.create_apex else None,
        )

        log.info("Creating CloudFront distribution")
        self.distribution = aws.cloudfront.Distribution(
            f"{name}-distro",
            comment=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}",
            enabled=True,
            is_ipv6_enabled=True,
            default_root_object=args.root_uri,
            logging_config=aws.cloudfront.DistributionLoggingConfigArgs(
                bucket="yokchi-cloudfront-logs.s3.amazonaws.com",
                include_cookies=False,
                prefix="logs/",
            ),
            aliases=(
                [self.domain_name, args.site_domain_name]
                if args.create_apex
                else [self.domain_name]
            ),
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
                    headers=["Authorization"],
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
            custom_error_responses=args.error_responses or [],
            opts=ResourceOptions(
                parent=self,
                depends_on=[certificate, validation],
                custom_timeouts={"delete": "30m"},
            ),
        )

        for site in self.site_origins:
            site.create_policy(self.distribution.id)

        if self.hosted_zone_id:
            log.info(f"Setting up DNS alias for hosted zone ID: {self.hosted_zone_id}")
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

            if args.create_apex:
                log.info("Creating apex domain alias")
                self.apex_alias = aws.route53.Record(
                    f"{name}-apex-alias",
                    name=args.site_domain_name,
                    type="A",
                    zone_id=self.hosted_zone_id,
                    aliases=[
                        aws.route53.RecordAliasArgs(
                            name=self.distribution.domain_name,
                            zone_id=self.distribution.hosted_zone_id.apply(
                                lambda id: id
                            ),
                            evaluate_target_health=True,
                        )
                    ],
                    opts=ResourceOptions(parent=self, depends_on=[self.distribution]),
                )
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

        log.info(f"Configured target origin ID: {target_origin_id}")
        return origins, caches, target_origin_id

    def set_up_certificate(
        self, name, domain_name, alternative_names: Optional[List[str]] = []
    ):
        certificate = aws.acm.Certificate(
            f"{name}-certificate",
            domain_name=domain_name,
            subject_alternative_names=alternative_names,
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
        )

        validation_options = certificate.domain_validation_options.apply(
            lambda options: options
        )

        dns_records = validation_options.apply(
            lambda options: [
                aws.route53.Record(
                    f"{name}-validation-record-{option.resource_record_name}",
                    name=option.resource_record_name,
                    zone_id=self.hosted_zone_id,
                    type=option.resource_record_type,
                    records=[option.resource_record_value],
                    ttl=60,
                    opts=ResourceOptions(parent=self),
                )
                for option in options
            ]
        )

        validation = dns_records.apply(
            lambda records: aws.acm.CertificateValidation(
                f"{name}-certificate-validation",
                certificate_arn=certificate.arn,
                validation_record_fqdns=[record.fqdn for record in records],
                opts=ResourceOptions(parent=self),
            )
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
    error_responses: Optional[list] = None,
    create_apex: Optional[bool] = False,
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
    return CDN(
        name,
        CDNArgs(
            sites=site_origins,
            apis=api_origins,
            hosted_zone_id=hosted_zone_id,
            site_domain_name=site_domain_name,
            error_responses=error_responses,
            create_apex=create_apex,
            root_uri=root_uri,
        ),
        opts,
    )
