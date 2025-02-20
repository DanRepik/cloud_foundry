import pulumi
import pulumi_aws as aws

from cloud_foundry.pulumi.ui_publisher import UIPublisher


class SiteBucket:
    def __init__(self, name: str, bucket_name: str = None, publishers: list = None):
        self.bucket_name = bucket_name or f"{name}-bucket"

        # Create the S3 bucket
        self.site_bucket = aws.s3.Bucket(
            self.bucket_name,
            bucket=self.bucket_name,
            force_destroy=True,
            tags={"Name": self.bucket_name},
        )

        # Bucket Ownership Controls
        bucket_ownership_controls = aws.s3.BucketOwnershipControls(
            f"{name}-ownership",
            bucket=self.site_bucket.id,
            rule={"object_ownership": "BucketOwnerPreferred"},
        )

        # Set ACL to private
        bucket_acl = aws.s3.BucketAclV2(
            f"{name}-acl",
            bucket=self.site_bucket.id,
            acl="private",
            opts=pulumi.ResourceOptions(depends_on=[bucket_ownership_controls]),
        )

        # CORS Configuration
        aws.s3.BucketCorsConfigurationV2(
            f"{name}-bucket-cors",
            bucket=self.site_bucket.id,
            cors_rules=[
                {
                    "allowed_headers": ["*"],
                    "allowed_methods": ["PUT", "POST"],
                    "allowed_origins": ["http://localhost:3030"],
                    "expose_headers": ["ETag"],
                    "max_age_seconds": 3000,
                }
            ],
        )

        # Enable Versioning
        aws.s3.BucketVersioningV2(
            f"{name}-bucket-versioning",
            bucket=self.site_bucket.id,
            versioning_configuration={"status": "Enabled"},
        )

        # Block all public access
        aws.s3.BucketPublicAccessBlock(
            f"{name}-access-block",
            bucket=self.site_bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
        )

        # Handle publishers if any
        if publishers:
            for publisher in publishers:
                UIPublisher(self.site_bucket, publisher)
