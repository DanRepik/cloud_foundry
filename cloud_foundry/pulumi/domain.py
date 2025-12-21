import pulumi
import pulumi_aws as aws
from pulumi import ComponentResource, ResourceOptions


class Domain(ComponentResource):
    def __init__(self, name, domain_name, hosted_zone_id, records, opts=None):
        super().__init__("cloud_foundry:domain:Domain", name, {}, opts)

        self.certificate = aws.acm.Certificate(
            f"{name}-certificate",
            domain_name=domain_name,
            validation_method="DNS",
            opts=ResourceOptions(parent=self),
        )

        # Retrieve the DNS validation options
        validationOptions = self.certificate.domain_validation_options.apply(
            lambda options: options[0]
        )

        # Create a Route 53 DNS record for validation
        validationRecord = aws.route53.Record(
            f"{name}-validation-record",
            name=validationOptions.resource_record_name,
            zone_id=hosted_zone_id,
            type=validationOptions.resource_record_type,
            records=[validationOptions.resource_record_value],
            ttl=60,
            opts=ResourceOptions(parent=self),
        )

        # Validate the ACM certificate
        self.validation = aws.acm.CertificateValidation(
            f"{name}-certificate-validation",
            certificate_arn=self.certificate.arn,
            validation_record_fqdns=[validationRecord.fqdn],
            opts=ResourceOptions(parent=self),
        )

        # Define the DNS record for Cognito User Pool
        self.cognito_dns_record = aws.route53.Record(
            f"{name}-cognito-dns-record",
            name=domain_name,
            type="CNAME",
            zone_id=hosted_zone_id,
            records=records,
            ttl=300,
            opts=ResourceOptions(parent=self),
        )

        self.register_outputs(
            {
                "certificate_arn": self.certificate.arn,
                "domain_name": self.certificate.domain_name,
                "validation_arn": self.validation.id,
            }
        )


def domain(
    name: str,
    domain_name: str,
    hosted_zone_id: str,
    opts: ResourceOptions = None,
) -> Domain:
    return Domain(name, domain_name, hosted_zone_id, opts)
