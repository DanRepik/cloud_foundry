import pulumi
import pulumi_aws as aws
import os
from mimetypes import guess_type

from cloud_foundry.utils.logger import logger

log = logger(__name__)


class UIPublisherArgs:
    def __init__(
        self, name: str, dist_dir: str, project_dir: str = ".", prefix: str = ""
    ):
        self.name = name
        self.dist_dir = dist_dir
        self.project_dir = project_dir
        self.prefix = prefix


class UIPublisher(pulumi.ComponentResource):
    """
    A Pulumi component to handle the publishing of UI assets to an S3 bucket.

    This component takes care of uploading files from a specified directory to an S3 bucket,
    setting the appropriate content type for each file based on its extension.
    """

    def __init__(
        self,
        bucket: aws.s3.Bucket,
        args: UIPublisherArgs,
        opts: pulumi.ResourceOptions = None,
    ):
        """
        Initialize the UIPublisher component.

        Args:
            name (str): The name of the component.
            bucket (aws.s3.Bucket): The S3 bucket to upload files to.
            args (UIPublisherArgs): The arguments for the UIPublisher component.
            opts (ResourceOptions): Optional resource options.
        """
        super().__init__("cloud_foundry:pulumi:UIPublisher", args.name, {}, opts)

        log.info(f"args: {args.__dict__}")
        self.bucket = bucket
        self.dist_dir = args.dist_dir or os.path.join(args.project_dir, "dist")

        self.upload_files(self.dist_dir, bucket, args.prefix)

        self.register_outputs({})

    def remap_path_to_s3(self, dir_base: str, key_base: str):
        """
        Remap local file paths to S3 keys.

        Args:
            dir_base (str): The base directory containing the files.
            key_base (str): The base key to prepend to the S3 keys.

        Returns:
            list[dict]: A list of dictionaries containing the local file paths and corresponding S3 keys.
        """
        log.info(f"remap: dir_base: {dir_base}")
        dir_base = os.path.abspath(dir_base)
        return [
            {
                "path": os.path.join(root, file),
                "key": os.path.join(
                    key_base, os.path.relpath(os.path.join(root, file), dir_base)
                ).replace("\\", "/"),
            }
            for root, _, files in os.walk(dir_base)
            for file in files
        ]

    def upload_files(self, dir: str, bucket: aws.s3.Bucket, key: str = ""):
        """
        Upload files from a directory to an S3 bucket.

        Args:
            dir (str): The directory containing the files to upload.
            bucket (aws.s3.Bucket): The S3 bucket to upload files to.
            key (str): The prefix to add to the S3 keys (optional).
        """
        for item in self.remap_path_to_s3(dir, key):
            content_type, _ = guess_type(item["path"])
            aws.s3.BucketObject(
                item["key"],
                bucket=bucket.id,
                key=item["key"],
                source=pulumi.FileAsset(item["path"]),
                content_type=content_type,
                opts=pulumi.ResourceOptions(parent=self, depends_on=[bucket]),
            )
