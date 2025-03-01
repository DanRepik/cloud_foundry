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
