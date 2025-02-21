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
        origin_path: str = "",
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

        # Determine the bucket type and extract the necessary
        log.info(f"args.bucket: {args.bucket}")
        if isinstance(args.bucket, aws.s3.Bucket):
            bucket_arn = args.bucket.arn
            bucket_id = args.bucket.id
            bucket_domain_name = args.bucket.bucket_regional_domain_name
        elif isinstance(args.bucket, SiteBucket):
            bucket_arn = args.bucket.bucket.arn
            bucket_id = args.bucket.bucket.id
            bucket_domain_name = args.bucket.bucket.bucket_regional_domain_name
        else:
            raise ValueError(
                "Invalid bucket type. Must be either aws.s3.Bucket or SiteBucket."
            )

        # Used to grant CloudFront access to the S3 bucket
        access_identity = aws.cloudfront.OriginAccessIdentity(
            f"{name}-oai",
            comment=f"Access Identity for {name}",
            opts=ResourceOptions(parent=self),
        )

        # Policy document to allow access from another account and CloudFront Origin Access Identity (OAI)
        allow_access_policy_document = pulumi.Output.all(
            bucket_arn, access_identity.iam_arn
        ).apply(
            lambda args: {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "delivery.logs.amazonaws.com"},
                        "Action": "s3:PutObject",
                        "Resource": f"{args[0]}/logs/*",
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": args[1]},
                        "Action": "s3:GetObject",
                        "Resource": f"{args[0]}/*",
                    },
                ],
            }
        )

        # Attach the bucket policy to allow access from another account and CloudFront OAI
        aws.s3.BucketPolicy(
            f"{name}-origin-cf-policy",
            bucket=bucket_id,
            policy=allow_access_policy_document.apply(json.dumps),
            opts=ResourceOptions(parent=self),
        )

        self.distribution_origin = aws.cloudfront.DistributionOriginArgs(
            domain_name=bucket_domain_name,
            origin_id=f"{name}-{args.name}-site",
            origin_path=args.origin_path,
            s3_origin_config=aws.cloudfront.DistributionOriginS3OriginConfigArgs(
                origin_access_identity=access_identity.cloudfront_access_identity_path,
            ),
            custom_headers=[],
        )

        if args.origin_shield_region:
            self.distribution_origin.origin_shield = (
                aws.cloudfront.DistributionOriginOriginShieldArgs(
                    enabled=True, origin_shield_region=args.origin_shield_region
                )
            )

        self.register_outputs({"distribution_origin": self.distribution_origin})
