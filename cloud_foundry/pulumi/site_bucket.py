import pulumi
import pulumi_aws as aws
from pulumi import ResourceOptions
from cloud_foundry.pulumi.ui_publisher import UIPublisher, UIPublisherArgs


def default_bucket_name(name: str) -> str:
    """Preserve the historical default S3 bucket naming scheme."""
    return f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}"


def is_production_stack(stack_name: str | None = None) -> bool:
    """Treat production-like stacks conservatively for destructive operations."""
    resolved = (stack_name or pulumi.get_stack()).strip().lower()
    return resolved in {"prod", "production"} or resolved.startswith("prod-")


class SiteBucketArgs:
    def __init__(self, bucket_name: str = None, publishers: list = None):
        self.bucket_name = bucket_name
        self.publishers = publishers


class SiteBucket(pulumi.ComponentResource):
    def __init__(self, name: str, args: SiteBucketArgs, opts: ResourceOptions = None):
        super().__init__("cloud_foundry:pulumi:SiteBucket", name, {}, opts)

        self.bucket_name = args.bucket_name or default_bucket_name(name)
        force_destroy = not is_production_stack()

        # BucketV2 does not manage bucket ACLs. That is required for modern S3
        # buckets with BucketOwnerEnforced ownership controls.
        self.bucket = aws.s3.BucketV2(
            self.bucket_name,
            bucket=self.bucket_name,
            force_destroy=force_destroy,
            tags={"Name": self.bucket_name},
            opts=ResourceOptions(parent=self),
        )
        self.ownership_controls = aws.s3.BucketOwnershipControls(
            f"{name}-ownership-controls",
            bucket=self.bucket.id,
            rule=aws.s3.BucketOwnershipControlsRuleArgs(
                object_ownership="BucketOwnerEnforced",
            ),
            opts=ResourceOptions(parent=self),
        )
        self.public_access_block = aws.s3.BucketPublicAccessBlock(
            f"{name}-public-access-block",
            bucket=self.bucket.id,
            block_public_acls=True,
            ignore_public_acls=True,
            block_public_policy=True,
            restrict_public_buckets=True,
            opts=ResourceOptions(parent=self),
        )

        # Handle publishers if any
        if args.publishers:
            for publisher in args.publishers:
                UIPublisher(
                    self.bucket,
                    UIPublisherArgs(**publisher),
                    opts=ResourceOptions(
                        parent=self,
                        depends_on=[
                            self.bucket,
                            self.ownership_controls,
                            self.public_access_block,
                        ],
                    ),
                )

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
