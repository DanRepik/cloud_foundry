import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from cloud_foundry.pulumi.ui_publisher import UIPublisher, UIPublisherArgs


class SiteBucketArgs:
    def __init__(self, bucket_name: str = None, publishers: list = None):
        self.bucket_name = bucket_name
        self.publishers = publishers


class SiteBucket(pulumi.ComponentResource):
    def __init__(self, name: str, args: SiteBucketArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:SiteBucket", name, {}, opts)

        self.bucket_name = (
            args.bucket_name or f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}"
        )

        # Create the S3 bucket
        self.bucket = aws.s3.Bucket(
            self.bucket_name,
            bucket=self.bucket_name,
            force_destroy=True,
            tags={"Name": self.bucket_name},
            opts=ResourceOptions(parent=self),
        )

        """
        # Bucket Ownership Controls
        bucket_ownership_controls = aws.s3.BucketOwnershipControls(
            f"{name}-ownership",
            bucket=self.bucket.id,
            rule={"object_ownership": "BucketOwnerPreferred"},
            opts=ResourceOptions(parent=self),
        )

        # Set ACL to private
        bucket_acl = aws.s3.BucketAclV2(
            f"{name}-acl",
            bucket=self.bucket.id,
            acl="private",
            opts=ResourceOptions(parent=self, depends_on=[bucket_ownership_controls]),
        )

        # CORS Configuration
        aws.s3.BucketCorsConfigurationV2(
            f"{name}-bucket-cors",
            bucket=self.bucket.id,
            cors_rules=[
                {
                    "allowed_headers": ["*"],
                    "allowed_methods": ["PUT", "POST"],
                    "allowed_origins": ["http://localhost:3030"],
                    "expose_headers": ["ETag"],
                    "max_age_seconds": 3000,
                }
            ],
            opts=ResourceOptions(parent=self),
        )

        # Enable Versioning
        aws.s3.BucketVersioningV2(
            f"{name}-bucket-versioning",
            bucket=self.bucket.id,
            versioning_configuration={"status": "Enabled"},
            opts=ResourceOptions(parent=self),
        )

        # Block all public access
        aws.s3.BucketPublicAccessBlock(
            f"{name}-access-block",
            bucket=self.bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
            opts=ResourceOptions(parent=self),
        )

        """
        # Handle publishers if any
        if args.publishers:
            for publisher in args.publishers:
                UIPublisher(self.bucket, UIPublisherArgs(**publisher))

        self.register_outputs(
            {
                "bucket_name": self.bucket_name,
                "bucket_id": self.bucket.id,
            }
        )


def site_bucket(
    name: str, bucket_name: str = None, publishers: list = None
) -> SiteBucket:
    return SiteBucket(
        name, SiteBucketArgs(bucket_name=bucket_name, publishers=publishers), None
    )
