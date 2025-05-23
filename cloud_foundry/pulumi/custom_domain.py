import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from logging import getLogger

log = getLogger(__name__)


def domain_from_subdomain(
    name: str, subdomain: str, hosted_zone_id
) -> pulumi.Output[str]:
    log.info(
        "Creating domain from subdomain:"
        + f" {subdomain} in hosted zone ID: {hosted_zone_id}"
    )
    hosted_zone = aws.route53.Zone.get(f"{name}-hosted-zone", id=hosted_zone_id)
    return pulumi.Output.concat(subdomain, ".", hosted_zone.name)


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

        alternative_names = [self.hosted_zone_name] if include_apex else []

        self.certificate = aws.acm.Certificate(
            f"{name}-certificate",
            domain_name=self.domain_name,
            subject_alternative_names=alternative_names,
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
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
        log.info(f"Creating DNS record for {name} with domain name: {self.domain_name}")
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

        pulumi.export(
            f"{name}-custom-domain-name",
            custom_domain.domain_name,
        )
