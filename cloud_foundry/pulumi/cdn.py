"""CloudFront CDN Component for Cloud Foundry.

This module provides a comprehensive CloudFront Content Delivery Network (CDN)
component with support for multiple origin types, custom domains, SSL/TLS
certificates, geo-restrictions, and advanced caching configurations.

Key Features:
    - Multiple origin types: S3 buckets, API Gateway REST APIs, custom domains
    - Automatic SSL/TLS certificate provisioning via ACM
    - Custom domain configuration with Route53 DNS
    - Geo-restriction support (whitelist/blacklist countries)
    - Origin Shield for improved cache hit ratios
    - Apex domain support
    - CORS and security headers via managed policies
    - Automatic cache behaviors for API origins

Origin Types:
    1. S3 Bucket (SiteOrigin):
        - Static website hosting
        - Origin Access Identity for secure access
        - Example: {"bucket": bucket_resource, "name": "site"}

    2. Domain Name (ApiOrigin):
        - Direct domain name for custom origins
        - Path-based routing with cache behaviors
        - Example: {"domain_name": "api.example.com", "path_pattern": "/api/*"}

    3. REST API (ApiOrigin):
        - API Gateway REST API integration
        - Automatic domain resolution
        - Example: {"rest_api": rest_api_resource, "path_pattern": "/api/*"}

Usage:
    from cloud_foundry.pulumi.cdn import CDN, CDNArgs

    # Basic CDN with API origin
    cdn = CDN(
        "my-cdn",
        CDNArgs(
            hosted_zone_id="Z1234567890ABC",
            subdomain="api",
            site_domain_name="example.com",
            origins=[
                {
                    "name": "api",
                    "domain_name": api.domain,
                    "path_pattern": "/api/*",
                    "origin_shield_region": "us-east-1"
                }
            ]
        )
    )

    # CDN with S3 bucket and API origin
    cdn = CDN(
        "multi-origin-cdn",
        CDNArgs(
            hosted_zone_id="Z1234567890ABC",
            subdomain="cdn",
            create_apex=True,
            site_domain_name="example.com",
            root_uri="index.html",
            origins=[
                {
                    "name": "site",
                    "bucket": s3_bucket,
                    "is_target_origin": True
                },
                {
                    "name": "api",
                    "domain_name": "api.example.com",
                    "path_pattern": "/api/*"
                }
            ],
            whitelist_countries=["US", "CA", "GB"]
        )
    )

Configuration:
    - hosted_zone_id: Route53 hosted zone for DNS records
    - subdomain: Subdomain for CDN distribution (e.g., "www", "cdn")
    - site_domain_name: Base domain name for apex domain support
    - create_apex: Create A record for apex domain (example.com)
    - origins: List of origin configurations (see Origin Types above)
    - error_responses: Custom error response configurations
    - root_uri: Default root object (e.g., "index.html")
    - whitelist_countries: ISO country codes to allow (exclusive with blacklist)
    - blacklist_countries: ISO country codes to block (default: CN, RU, CU, KP, IR, BY)

Outputs:
    - distribution: CloudFront Distribution resource
    - domain_name: CDN domain name (custom domain or CloudFront domain)
    - dns_alias: Route53 A record for custom domain
    - apex_alias: Route53 A record for apex domain (if create_apex=True)
"""

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
    """Configuration arguments for CDN component.

    Attributes:
        origins: List of origin configurations. Each origin dict can contain:
            - name (str): Unique identifier for the origin
            - bucket (aws.s3.Bucket): S3 bucket for static site hosting
            - domain_name (str|Output): Custom domain name for API origin
            - rest_api (RestAPI): API Gateway REST API resource
            - path_pattern (str): Path pattern for cache behavior (e.g., "/api/*")
            - origin_path (str): Optional path prefix on origin
            - origin_shield_region (str): AWS region for Origin Shield
            - is_target_origin (bool): Whether this is the default origin
            - api_key_password (str): Optional API key for custom header
        create_apex: Whether to create DNS record for apex domain (default: False)
        hosted_zone_id: Route53 hosted zone ID for DNS records
        subdomain: Subdomain for the CDN (e.g., "www", "cdn", "api")
        site_domain_name: Base domain name for apex domain creation
        error_responses: List of custom error response configurations
        root_uri: Default root object for distribution (e.g., "index.html")
        whitelist_countries: ISO country codes to allow (exclusive with blacklist)
        blacklist_countries: ISO country codes to block (default: CN, RU, CU, KP, IR, BY)
    """

    def __init__(
        self,
        origins: Optional[List[dict]] = None,
        create_apex: Optional[bool] = False,
        hosted_zone_id: Optional[str] = None,
        subdomain: Optional[str] = None,
        site_domain_name: Optional[str] = None,
        error_responses: Optional[list] = None,
        root_uri: Optional[str] = None,
        whitelist_countries: Optional[List[str]] = None,
        blacklist_countries: Optional[List[str]] = None,
    ):
        self.origins = origins
        self.create_apex = create_apex
        self.hosted_zone_id = hosted_zone_id
        self.subdomain = subdomain
        self.site_domain_name = site_domain_name
        self.error_responses = error_responses
        self.root_uri = root_uri
        self.whitelist_countries = whitelist_countries
        self.blacklist_countries = blacklist_countries


class CDN(pulumi.ComponentResource):
    """CloudFront CDN Component Resource.

    Creates a CloudFront distribution with:
    - Multiple origin support (S3, API Gateway, custom domains)
    - SSL/TLS certificate provisioned via ACM
    - Custom domain with Route53 DNS configuration
    - Geo-restriction support
    - Origin Shield for improved performance
    - Managed CORS and security headers
    - Path-based cache behaviors for API origins

    The component automatically:
    - Provisions and validates ACM certificate
    - Creates Route53 DNS records for custom domain
    - Configures origin-specific cache behaviors
    - Sets up S3 bucket policies for OAI access
    - Applies geo-restrictions

    Attributes:
        distribution: CloudFront Distribution resource
        domain_name: CDN domain name (custom or CloudFront)
        dns_alias: Route53 A record for subdomain
        apex_alias: Route53 A record for apex domain (if create_apex=True)
        site_origins: List of SiteOrigin resources
        hosted_zone_id: Route53 hosted zone ID
        subdomain: CDN subdomain

    Example:
        cdn = CDN(
            "my-cdn",
            CDNArgs(
                hosted_zone_id="Z123456",
                subdomain="api",
                origins=[
                    {
                        "name": "api",
                        "domain_name": legis_api.domain,
                        "path_pattern": "/api/*",
                        "origin_shield_region": "us-east-1"
                    }
                ]
            )
        )
    """

    def __init__(self, name: str, args: CDNArgs, opts: ResourceOptions = None):
        """Initialize CDN component.

        Args:
            name: Resource name for the CDN
            args: CDN configuration arguments
            opts: Pulumi resource options
        """
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

        aliases_list = (
            [self.domain_name, args.site_domain_name]
            if args.create_apex
            else [self.domain_name]
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
            aliases=aliases_list,
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
        """Process and configure CDN origins.

        Processes the origin configurations and creates appropriate origin resources
        (SiteOrigin for S3, ApiOrigin for APIs/domains). Determines the default
        target origin and configures cache behaviors.

        Args:
            name: Base name for origin resources
            origins: List of origin configuration dicts with keys:
                - bucket: S3 bucket for static sites
                - domain_name: Custom domain name string
                - rest_api: RestAPI resource
                - name: Origin identifier
                - path_pattern: Cache behavior path pattern
                - origin_path: Path prefix on origin
                - origin_shield_region: Origin Shield region
                - is_target_origin: Mark as default origin
                - api_key_password: API key for custom header

        Returns:
            Tuple of (cdn_origins, caches, target_origin_id):
                - cdn_origins: List of DistributionOriginArgs
                - caches: List of DistributionOrderedCacheBehaviorArgs
                - target_origin_id: Default origin ID

        Raises:
            ValueError: If origin configuration is invalid or domain cannot be resolved
        """
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
                cdn_origin = ApiOrigin(
                    f"{name}-{origin["name"]}",
                    domain_name=origin["domain_name"],
                    path_pattern=origin.get("path_pattern"),
                    origin_path=origin.get("origin_path"),
                    shield_region=origin.get("origin_shield_region"),
                )
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
        """Provision and validate ACM certificate for custom domain.

        Creates an ACM certificate with DNS validation via Route53. Automatically
        creates validation DNS records and waits for certificate validation.

        Args:
            name: Resource name prefix
            domain_name: Primary domain name for certificate
            alternative_names: List of Subject Alternative Names (SANs)

        Returns:
            Tuple of (certificate, validation) resources

        Raises:
            ValueError: If hosted_zone_id is not configured
        """
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
        """Configure custom domain for API Gateway REST API.

        Creates ACM certificate, API Gateway domain name, base path mapping,
        and Route53 DNS record for a custom domain pointing to an API Gateway.

        Args:
            name: Resource name prefix
            hosted_zone_id: Route53 hosted zone ID for DNS
            domain_name: Custom domain name
            stage_name: API Gateway stage name
            rest_api_id: API Gateway REST API ID

        Returns:
            The configured domain name string
        """
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
        """Find Route53 hosted zone ID by domain name.

        Placeholder method for looking up hosted zone ID dynamically.

        Args:
            name: Domain name to search for

        Returns:
            Hosted zone ID string

        Note:
            This method is not yet implemented. Pass hosted_zone_id
            directly in CDNArgs instead.
        """
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
    """Factory function to create a CDN component.

    Convenience function for creating a CDN without explicitly constructing
    CDNArgs. Wraps the CDN component resource initialization.

    Args:
        name: Resource name for the CDN
        origins: List of origin configuration dicts
        hosted_zone_id: Route53 hosted zone ID for custom domain
        subdomain: Subdomain for CDN (e.g., "www", "cdn")
        error_responses: Custom error response configurations
        create_apex: Create apex domain A record (default: False)
        root_uri: Default root object (e.g., "index.html")
        opts: Pulumi resource options

    Returns:
        CDN component resource instance

    Example:
        my_cdn = cdn(
            "website-cdn",
            origins=[
                {
                    "name": "site",
                    "bucket": website_bucket,
                    "is_target_origin": True
                }
            ],
            hosted_zone_id="Z123456",
            subdomain="www",
            root_uri="index.html"
        )
    """
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
