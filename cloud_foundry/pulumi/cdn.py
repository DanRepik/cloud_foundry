import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from typing import List, Optional

from cloud_foundry.pulumi.cdn_api_origin import ApiOrigin
from cloud_foundry.pulumi.cdn_site_origin import SiteOrigin
from cloud_foundry.pulumi.custom_domain import CustomCertificate, domain_from_subdomain
from cloud_foundry.pulumi.rest_api import RestAPI
from cloud_foundry.utils.logger import logger

log = logger(__name__)

DEFAULT_BLACKLIST_COUNTRIES = [
    "CN",  # Example: Block China
    "RU",  # Example: Block Russia
    "CU",  # Example: Block Cuba
    "KP",  # Example: Block North Korea
    "IR",  # Example: Block Iran
    "BY",  # Example: Block Belarus
]


class CDNArgs:
    def __init__(
        self,
        origins: Optional[List[dict]] = None,
        create_apex: Optional[bool] = False,
        hosted_zone_id: Optional[str] = None,
        subdomain: Optional[str] = None,
        error_responses: Optional[list] = None,
        root_uri: Optional[str] = None,
        whitelist_countries: Optional[List[str]] = None,
        blacklist_countries: Optional[List[str]] = None,
    ):
        self.origins = origins
        self.create_apex = create_apex
        self.hosted_zone_id = hosted_zone_id
        self.subdomain = subdomain
        self.error_responses = error_responses
        self.root_uri = root_uri
        self.whitelist_countries = whitelist_countries
        self.blacklist_countries = blacklist_countries


class CDN(pulumi.ComponentResource):
    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:CDN", name, {}, opts)

        self.hosted_zone_id = args.hosted_zone_id
        log.info(f"subdomain: {args.subdomain}")
        self.subdomain = args.subdomain or pulumi.get_stack()
        self.domain_name = domain_from_subdomain(
            name, self.subdomain, self.hosted_zone_id
        )

        custom_certificate = CustomCertificate(
            name,
            hosted_zone_id=self.hosted_zone_id,
            subdomain=self.subdomain,
            include_apex=args.create_apex,
        )

        log.info("Creating CloudFront distribution")

        log.info(
            "aliases:"
            + {
                (
                    [self.domain_name, args.site_domain_name]
                    if args.create_apex
                    else [self.domain_name]
                )
            }
        )

        origins, caches, target_origin_id = self.get_origins(name, args.origins)
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
                    restriction_type=(
                        "whitelist" if args.whitelist_countries else "blacklist"
                    ),
                    locations=(
                        args.whitelist_countries
                        if args.whitelist_countries
                        else args.blacklist_countries or DEFAULT_BLACKLIST_COUNTRIES
                    ),
                )
            ),
            viewer_certificate={
                "acm_certificate_arn": custom_certificate.certificate.arn,
                "ssl_support_method": "sni-only",
                "minimum_protocol_version": "TLSv1.2_2021",
            },
            origins=origins,
            custom_error_responses=args.error_responses or [],
            opts=ResourceOptions(
                parent=self,
                depends_on=[custom_certificate],
                custom_timeouts={"delete": "30m"},
            ),
        )

        for site in self.site_origins:
            site.create_policy(self.distribution.id)

        if self.hosted_zone_id:
            log.info(f"Setting up DNS alias for hosted zone ID: {self.hosted_zone_id}")
            self.dns_alias = aws.route53.Record(
                f"{name}-alias",
                name=domain_from_subdomain(
                    f"{name}-cdn", self.subdomain, self.hosted_zone_id
                ),
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

    def get_origins(self, name: str, origins: List[dict]):
        target_origin_id = None
        cdn_origins = []
        caches = []
        self.site_origins = []

        for origin in origins:

            log.info(f"Configuring origin: {origin}")
            cdn_origin = None
            if "bucket" in origin:
                cdn_origin = SiteOrigin(
                    f"{name}-{origin["name"]}",
                    bucket=origin["bucket"],
                    origin_path=origin.get("origin_path"),
                    origin_shield_region=origin.get("origin_shield_region"),
                )
                cdn_origins.append(cdn_origin.distribution_origin)
                self.site_origins.append(cdn_origin)

            elif "domain_name" in origin:
                cdn_origin = ApiOrigin(f"{name}-{origin["name"]}", origin)
                cdn_origins.append(cdn_origin.distribution_origin)
                caches.append(cdn_origin.cache_behavior)

            elif "rest_api" in origin:
                rest_api = origin["rest_api"]

                domain_name = None
                if isinstance(rest_api, RestAPI):
                    domain_name = rest_api.domain
                    if not domain_name:
                        domain_name = rest_api.create_custom_domain(
                            self.hosted_zone_id,
                            pulumi.Output.concat(origin["name"], "-", self.subdomain),
                        )
                else:
                    if isinstance(rest_api, aws.apigateway.RestApi):
                        domain_name = self.setup_custom_domain(
                            name=origin["name"],
                            hosted_zone_id=self.hosted_zone_id,
                            domain_name=pulumi.Output.concat(
                                origin["name"], "-", pulumi.get_stack()
                            ),
                            stage_name=origin.rest_api.name,
                            rest_api_id=origin.rest_api.id,
                        )

                if domain_name is None:
                    raise ValueError(
                        f"Could not resolve domain name for origin: {origin["name"]}"
                    )

                cdn_origin = ApiOrigin(
                    f"{name}-{origin["name"]}",
                    domain_name=domain_name,
                    path_pattern=origin.get("path_pattern"),
                    origin_path=origin.get("origin_path"),
                    shield_region=origin.get("shield_region"),
                    api_key_password=origin.get("api_key_password"),
                )
                cdn_origins.append(cdn_origin.distribution_origin)
                caches.append(cdn_origin.cache_behavior)

            if cdn_origin is None:
                raise ValueError(f"Invalid origin configuration: {origin}")

            if "is_target_origin" in origin and origin["is_target_origin"]:
                target_origin_id = cdn_origin.origin_id

        if target_origin_id is None:
            target_origin_id = cdn_origins[0].origin_id

        log.info(f"Configured target origin ID: {target_origin_id}")
        return cdn_origins, caches, target_origin_id

    def set_up_certificate(
        self, name, domain_name, alternative_names: Optional[List[str]] = None
    ):
        if not self.hosted_zone_id:
            raise ValueError(
                "Hosted zone ID is required for custom domain setup. "
                + f"domain_name: {domain_name}."
            )

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
        aws.apigateway.BasePathMapping(
            f"{name}-base-path-map",
            rest_api=rest_api_id,
            stage_name=stage_name,
            domain_name=custom_domain.domain_name,
            opts=pulumi.ResourceOptions(parent=self, depends_on=[custom_domain]),
        )

        # Define the DNS record
        aws.route53.Record(
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
    origins: list[dict],
    hosted_zone_id: Optional[str] = None,
    subdomain: Optional[str] = None,
    error_responses: Optional[list] = None,
    create_apex: Optional[bool] = False,
    root_uri: Optional[str] = None,
    opts: ResourceOptions = None,
) -> CDN:

    return CDN(
        name,
        CDNArgs(
            origins=origins,
            hosted_zone_id=hosted_zone_id,
            subdomain=subdomain,
            error_responses=error_responses,
            create_apex=create_apex,
            root_uri=root_uri,
        ),
        opts,
    )
