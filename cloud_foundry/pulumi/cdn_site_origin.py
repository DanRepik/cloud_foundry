import json
import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions

from cloud_foundry.pulumi.site_bucket import SiteBucket
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class SiteOriginArgs:
    def __init__(
        self,
        *,
        bucket,
        name: str,
        origin_path: str = None,
        origin_shield_region: str = None,
        is_target_origin: bool = False,
    ):
        self.bucket = bucket
        self.name = name
        self.origin_path = origin_path
        self.origin_shield_region = origin_shield_region
        self.is_target_origin = is_target_origin
        self.origin_id = f"{name}-site"


class SiteOrigin(pulumi.ComponentResource):
    """
    Create a site origin for CloudFront distribution.

    :param name: The name of the site origin.
    :param args: The arguments for setting up the site origin.
    :return: The CloudFront distribution origin.
    """

    def __init__(self, name: str, args: SiteOriginArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:SiteOrigin", name, {}, opts)

        self.name = name
        # Determine the bucket type and extract the necessary
        if isinstance(args.bucket, aws.s3.Bucket):
            self.bucket = args.bucket
        elif isinstance(args.bucket, SiteBucket):
            self.bucket = args.bucket.bucket
        else:
            raise ValueError(
                "Invalid bucket type. Must be either aws.s3.Bucket or SiteBucket."
            )

        # Create Origin Access Control
        origin_access_control = aws.cloudfront.OriginAccessControl(
            f"{name}-origin-access-control",
            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}",
            origin_access_control_origin_type="s3",
            signing_behavior="always",
            signing_protocol="sigv4",
            opts=ResourceOptions(parent=self),
        )

        self.bucket.bucket_regional_domain_name.apply(lambda domain_name: log.info(f"bucket_regional_domain_name: {domain_name}"))

        self.distribution_origin = aws.cloudfront.DistributionOriginArgs(
            domain_name=self.bucket.bucket_regional_domain_name,
            origin_id=f"{self.name}-site",
            origin_access_control_id=origin_access_control.id,
            origin_path=args.origin_path,
            s3_origin_config=aws.cloudfront.DistributionOriginS3OriginConfigArgs(
                origin_access_identity=""
            ),
        )

        if args.origin_shield_region:
            self.distribution_origin.origin_shield = (
                aws.cloudfront.DistributionOriginOriginShieldArgs(
                    enabled=True, origin_shield_region=args.origin_shield_region
                )
            )

        log.info(f"distribution_origin: {vars(self.distribution_origin)}")
        self.register_outputs({"distribution_origin": self.distribution_origin})

    def create_distribution_origin(self):
        return self.distribution_origin
    
    def create_policy(self, distiribution_id):
        # Create S3 Bucket Policy
        bucket_policy = aws.s3.BucketPolicy(
            f"{self.name}-bucket-policy",
            bucket=self.bucket.bucket,
            policy=pulumi.Output.all(self.bucket.arn, distiribution_id, aws.get_caller_identity().account_id).apply(
            lambda args: json.dumps(
                {
                "Version": "2012-10-17",
                "Statement": [
                    {
                    "Effect": "Allow",
                    "Principal": {"Service": "cloudfront.amazonaws.com"},
                    "Action": "s3:GetObject",
                    "Resource": f"{args[0]}/*",
                    "Condition": {
                        "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudfront::{args[2]}:distribution/{args[1]}"
                        }
                    },
                    }
                ],
                }
            )
            ),
            opts=ResourceOptions(parent=self),
        )

