import pulumi
import pulumi_aws as aws
import os
from mimetypes import guess_type

from cloud_foundry.utils.logger import logger

log = logger(__name__)


class UIPublisher:
    def __init__(self, bucket: aws.s3.Bucket, args: dict):
        log.info(f"args: {args}")
        self.bucket = bucket
        self.dist_dir = args.get(
            "dist_dir", os.path.join(args.get("project_dir", "."), "dist")
        )

        self.upload_files(self.dist_dir, bucket, args.get("prefix", ""))

    def remap_path_to_s3(self, dir_base: str, key_base: str):
        log.info(f"remap: dir_base: {dir_base}")
        dir_base = os.path.abspath(dir_base)
        return [
            {
                "path": os.path.join(root, file),
                "key": os.path.relpath(os.path.join(root, file), dir_base).replace(
                    "\\", "/"
                ),
            }
            for root, _, files in os.walk(dir_base)
            for file in files
        ]

    def upload_files(self, dir: str, bucket: aws.s3.Bucket, key: str = ""):
        for item in self.remap_path_to_s3(dir, key):
            aws.s3.BucketObject(
                item["key"],
                bucket=bucket.id,
                key=item["key"],
                source=pulumi.FileAsset(item["path"]),
                content_type=guess_type(item["path"])[0],
            )
