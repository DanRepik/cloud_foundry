import pulumi
import pulumi_aws as aws
from typing import List, Optional
from cloud_foundry.utils.logger import logger

log = logger(__name__)

class ContentRepository(pulumi.ComponentResource):
    site_bucket: aws.s3.Bucket

    def __init__(self, name: str, bucket_name: Optional[str] = None, publishers: Optional[List[dict]] = None, opts: pulumi.ResourceOptions = None):
        super().__init__("cloud_forge:origin:ContentRepository", name, {}, opts)

        # Define the bucket name (use the provided or generate a default)
        final_bucket_name = bucket_name or self._generate_bucket_name(name)

        log.info(f"Creating S3 bucket: {final_bucket_name}")

        # Create the S3 bucket
        self.site_bucket = aws.s3.Bucket(
            resource_name=f"{name}-bucket",
            bucket=final_bucket_name,
            force_destroy=True,  # Assuming this is similar to the `is_local` flag in the original code
            tags={"Name": f"{name}-bucket"}
        )

        # Ownership controls: BucketOwnerPreferred
        bucket_ownership_controls = aws.s3.BucketOwnershipControls(
            resource_name=f"{name}-ownership",
            bucket=self.site_bucket.bucket,
            rule=aws.s3.BucketOwnershipControlsRuleArgs(
                object_ownership="BucketOwnerPreferred"
            )
        )

        # Set ACL to private (depends on ownership controls)
        bucket_acl = aws.s3.BucketAclV2(
            resource_name=f"{name}-acl",
            acl="private",
            bucket=self.site_bucket.bucket,
            opts=pulumi.ResourceOptions(depends_on=[bucket_ownership_controls])
        )

        # CORS Configuration
        aws.s3.BucketCorsConfigurationV2(
            resource_name=f"{name}-bucket-cors",
            bucket=self.site_bucket.id,
            cors_rules=[aws.s3.BucketCorsConfigurationV2RuleArgs(
                allowed_headers=["*"],
                allowed_methods=["PUT", "POST"],
                allowed_origins=["http://localhost:3030"],
                expose_headers=["ETag"],
                max_age_seconds=3000,
            )]
        )

        # Enable versioning
        aws.s3.BucketVersioning(
            resource_name=f"{name}-bucket-versioning",
            bucket=self.site_bucket.id,
            versioning_configuration=aws.s3.BucketVersioningVersioningConfigurationArgs(
                status="Enabled"
            )
        )

        # Block all public access
        aws.s3.BucketPublicAccessBlock(
            resource_name=f"{name}-access-block",
            bucket=self.site_bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True
        )

        # Handle publishers (if provided)
        if publishers:
            for publisher in publishers:
                self._create_publisher(name, publisher)

        # Register the output for this component
        self.register_outputs({
            "bucket": self.site_bucket.bucket,
            "bucket_arn": self.site_bucket.arn,
        })

    def _generate_bucket_name(self, name: str) -> str:
        """
        Generate a bucket name using a standard format.
        """
        return f"{name}-bucket-{pulumi.get_project()}-{pulumi.get_stack()}"

    def _create_publisher(self, name: str, publisher: dict):
        """
        Create a UIPublisher for the bucket based on the provided publisher args.
        """
        log.info(f"Creating publisher: {publisher['name']} for bucket {self.site_bucket.bucket}")
        # Assuming UIPublisher takes in site_bucket and publisher as arguments, 
        # adapt this to whatever the publisher logic requires.
        UIPublisher(
            name=f"{name}-{publisher['name']}",
            bucket=self.site_bucket,
            publisher_args=publisher
        )

# Example usage
site_bucket = SiteBucket(
    name="my-site-bucket",
    bucket_name="my-custom-bucket",
    publishers=[
        {"name": "publisher1", "some_param": "value1"},
        {"name": "publisher2", "some_param": "value2"}
    ]
)
