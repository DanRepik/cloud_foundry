import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from logging import getLogger

log = getLogger(__name__)

hosted_zones = {}


def get_hosted_zone(hosted_zone_id: str) -> aws.route53.Zone:
    """
    Retrieve the hosted zone ID from the environment variable or create a new one.
    """
    if hosted_zone_id not in hosted_zones:
        hosted_zones[hosted_zone_id] = aws.route53.Zone.get(
            f"hosted-zone-{hosted_zone_id}", id=hosted_zone_id
        )
    return hosted_zones[hosted_zone_id]


def domain_from_subdomain(
    name: str, subdomain: str, hosted_zone_id
) -> pulumi.Output[str]:
    log.info(
        "Creating domain from subdomain:"
        + f" {subdomain} in hosted zone ID: {hosted_zone_id}"
    )
    return pulumi.Output.concat(subdomain, ".", get_hosted_zone(hosted_zone_id).name)


class CustomCertificate(pulumi.ComponentResource):
    def __init__(
        self,
        name: str,
        hosted_zone_id: str,
        subdomain: str,
        include_apex: bool = False,
        opts: ResourceOptions = None,
    ):
        super().__init__("cloud_foundry:apigw:CustomCertificate", name, {}, opts)

        log.info(f"Hosted zone ID: {hosted_zone_id}")
        self.domain_name = domain_from_subdomain(
            f"{name}-cert", subdomain, hosted_zone_id
        )

        alternative_names = (
            [get_hosted_zone(hosted_zone_id).name] if include_apex else []
        )

        self.certificate = pulumi.Output.all(self.domain_name, alternative_names).apply(
            lambda args: self._create_certificate(name, args[0], args[1])
        )

        validation_options = self.certificate.domain_validation_options.apply(
            lambda options: options
        )

        dns_records = validation_options.apply(
            lambda options: [
                aws.route53.Record(
                    f"{name}-{option.resource_record_name}",
                    name=option.resource_record_name,
                    zone_id=hosted_zone_id,
                    type=option.resource_record_type,
                    records=[option.resource_record_value],
                    ttl=60,
                    opts=ResourceOptions(parent=self),
                )
                for option in options
            ]
        )

        self.validation = dns_records.apply(
            lambda records: aws.acm.CertificateValidation(
                f"{name}-certificate-validation",
                certificate_arn=self.certificate.arn,
                validation_record_fqdns=[record.fqdn for record in records],
                opts=ResourceOptions(parent=self),
            )
        )

    def _create_certificate(self, name: str, domain_name: str, alternative_names: list):
        log.info(
            f"Creating certificate for domain: {domain_name} "
            + f"with alternative names: {alternative_names}"
        )
        return aws.acm.Certificate(
            f"{name}-certificate",
            domain_name=self.domain_name,
            subject_alternative_names=alternative_names,
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
        )


class CustomGatewayDomain(CustomCertificate):
    def __init__(
        self,
        name: str,
        hosted_zone_id: str,
        subdomain: str,
        rest_api_id: str,
        stage_name: str,
        opts: ResourceOptions = None,
    ):
        super().__init__(
            name=name,
            hosted_zone_id=hosted_zone_id,
            subdomain=subdomain,
            opts=opts,
        )

        custom_domain = aws.apigateway.DomainName(
            f"{name}-custom-domain",
            domain_name=self.domain_name,
            regional_certificate_arn=self.certificate.arn,
            endpoint_configuration={
                "types": "REGIONAL",
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[self.validation]),
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
        log.info(f"Creating DNS record for {name} with subdomain: {subdomain}")
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

        self.register_outputs(
            {
                "domain": custom_domain.domain_name,
            }
        )
