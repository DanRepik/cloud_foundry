import concurrent.futures
import hashlib
import os
from mimetypes import guess_type

import pulumi
from pulumi.dynamic import CreateResult, DiffResult, Resource, ResourceProvider, UpdateResult

from cloud_foundry.utils.logger import logger

log = logger(__name__)

# Fields of a file's manifest entry that decide whether it has to be
# (re)uploaded. The local path is left out on purpose: the same build checked
# out somewhere else must not look like a change.
_OBJECT_FIELDS = ("sha256", "content_type", "cache_control")

_UPLOAD_WORKERS = 16
_DELETE_BATCH = 1000  # DeleteObjects limit


class UIPublisherArgs:
    def __init__(
        self, name: str, dist_dir: str, project_dir: str = ".", prefix: str = ""
    ):
        self.name = name
        self.dist_dir = dist_dir
        self.project_dir = project_dir
        self.prefix = prefix


def _s3_client(connection: dict):
    import boto3
    from botocore.config import Config

    session = boto3.session.Session(
        profile_name=connection.get("profile") or None,
        aws_access_key_id=connection.get("access_key") or None,
        aws_secret_access_key=connection.get("secret_key") or None,
        aws_session_token=connection.get("token") or None,
        region_name=connection.get("region") or None,
    )
    addressing = "path" if connection.get("path_style") else "auto"
    return session.client(
        "s3",
        endpoint_url=connection.get("endpoint_url") or None,
        config=Config(s3={"addressing_style": addressing}),
    )


def _changed_keys(old_files: dict, new_files: dict) -> list[str]:
    """Keys that are new or whose content or headers changed."""
    return sorted(
        key
        for key, entry in new_files.items()
        if any(
            (old_files.get(key) or {}).get(field) != entry.get(field)
            for field in _OBJECT_FIELDS
        )
    )


def _upload(client, props: dict, keys: list[str]) -> None:
    def put(key: str) -> None:
        entry = props["files"][key]
        extra = {"CacheControl": entry["cache_control"]}
        if entry.get("content_type"):
            extra["ContentType"] = entry["content_type"]
        with open(os.path.join(props["source_dir"], entry["path"]), "rb") as body:
            client.put_object(Bucket=props["bucket"], Key=key, Body=body, **extra)

    with concurrent.futures.ThreadPoolExecutor(_UPLOAD_WORKERS) as pool:
        # list() re-raises the first upload error, failing the operation.
        list(pool.map(put, keys))


def _delete(client, bucket: str, keys: list[str]) -> None:
    for start in range(0, len(keys), _DELETE_BATCH):
        batch = keys[start : start + _DELETE_BATCH]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        if response.get("Errors"):
            raise RuntimeError(f"failed to delete from {bucket}: {response['Errors'][:5]}")


def _outputs(props: dict) -> dict:
    return {**props, "object_count": len(props["files"])}


class SiteFilesProvider(ResourceProvider):
    """Keeps a bucket prefix in step with a local build directory as ONE
    Pulumi resource. Each file used to be its own BucketObjectv2, so a site
    rebuild meant hundreds of resource steps -- each followed by a full state
    checkpoint write, which on the DIY S3 backend dominated deploy time."""

    def diff(self, _id: str, olds: dict, news: dict) -> DiffResult:
        replaces = [name for name in ("bucket", "prefix") if olds.get(name) != news.get(name)]
        old_files, new_files = olds.get("files") or {}, news.get("files") or {}
        changed = bool(_changed_keys(old_files, new_files)) or set(old_files) != set(new_files)
        return DiffResult(
            changes=bool(replaces) or changed,
            replaces=replaces,
            delete_before_replace=False,
        )

    def create(self, props: dict) -> CreateResult:
        client = _s3_client(props["connection"])
        _upload(client, props, sorted(props["files"]))
        return CreateResult(
            id_=f"{props['bucket']}/{props['prefix']}", outs=_outputs(props)
        )

    def update(self, _id: str, olds: dict, news: dict) -> UpdateResult:
        client = _s3_client(news["connection"])
        old_files = olds.get("files") or {}
        _upload(client, news, _changed_keys(old_files, news["files"]))
        # Uploads first, so a new page never points at an asset that isn't
        # there yet; then drop what the new build no longer has.
        _delete(client, news["bucket"], sorted(set(old_files) - set(news["files"])))
        return UpdateResult(outs=_outputs(news))

    def delete(self, _id: str, props: dict) -> None:
        # Leaves the bucket empty of our objects, so a bucket without
        # force_destroy (production) can still be deleted after this.
        client = _s3_client(props["connection"])
        try:
            _delete(client, props["bucket"], sorted(props.get("files") or {}))
        except client.exceptions.NoSuchBucket:
            pass


class SiteFiles(Resource):
    object_count: pulumi.Output[int]

    def __init__(self, name: str, props: dict, opts: pulumi.ResourceOptions = None):
        super().__init__(
            SiteFilesProvider(),
            name,
            {**props, "object_count": None},
            opts,
        )


def _connection() -> dict:
    """How the sync reaches S3. A dynamic provider talks to AWS through boto3
    rather than the pulumi-aws provider, so the stack's aws: config (region,
    profile, static keys, LocalStack endpoints) is handed over explicitly."""
    config = pulumi.Config("aws")
    endpoints = config.get_object("endpoints") or []
    s3_endpoint = next(
        (entry["s3"] for entry in endpoints if isinstance(entry, dict) and entry.get("s3")),
        None,
    )
    connection = {
        # None falls back to AWS_REGION / the profile, as the aws provider does.
        "region": config.get("region"),
        "profile": config.get("profile"),
        "endpoint_url": s3_endpoint,
        "path_style": (config.get("s3UsePathStyle") or "").lower() == "true",
    }
    access_key, secret_key = config.get("accessKey"), config.get_secret("secretKey")
    if access_key and secret_key is not None:
        connection["access_key"] = access_key
        connection["secret_key"] = secret_key
        token = config.get_secret("token")
        if token is not None:
            connection["token"] = token
    return connection


class UIPublisher(pulumi.ComponentResource):
    """
    A Pulumi component to handle the publishing of UI assets to an S3 bucket.

    All files under the build directory are published by a single resource
    that uploads only new or changed files (by content hash, content type and
    cache policy) and deletes files the build no longer contains.
    """

    def __init__(
        self,
        bucket,
        args: UIPublisherArgs,
        opts: pulumi.ResourceOptions = None,
    ):
        """
        Initialize the UIPublisher component.

        Args:
            bucket: The S3 bucket resource to upload files to.
            args (UIPublisherArgs): The arguments for the UIPublisher component.
            opts (ResourceOptions): Optional resource options.
        """
        super().__init__("cloud_foundry:pulumi:UIPublisher", args.name, {}, opts)

        log.info(f"args: {args.__dict__}")
        self.bucket = bucket
        self.dist_dir = args.dist_dir or os.path.join(args.project_dir, "dist")

        self.files = self.upload_files(self.dist_dir, bucket, args.prefix)

        self.register_outputs({})

    @staticmethod
    def cache_control_for_key(key: str) -> str:
        """Return a conservative cache policy for a static site object."""
        normalized = key.lower().lstrip("/")

        if normalized == "_payload.json" or normalized.endswith("/_payload.json"):
            return "public, max-age=31536000, immutable"

        if normalized.startswith("_nuxt/"):
            return "public, max-age=31536000, immutable"

        if normalized.endswith(".html"):
            return "public, max-age=300, s-maxage=86400, stale-while-revalidate=3600"

        if normalized.endswith(
            (
                ".js",
                ".mjs",
                ".css",
                ".svg",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".ico",
                ".woff",
                ".woff2",
                ".ttf",
                ".otf",
                ".eot",
            )
        ):
            return "public, max-age=31536000, immutable"

        if normalized.endswith((".json", ".xml", ".txt", ".webmanifest")):
            return "public, max-age=3600, stale-while-revalidate=300"

        return "public, max-age=3600"

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

    def build_manifest(self, dir: str, key: str = "") -> dict:
        """Map each S3 key to its file (relative to ``dir``), content hash,
        content type and cache policy."""
        dir_base = os.path.abspath(dir)
        manifest = {}
        for item in self.remap_path_to_s3(dir_base, key):
            with open(item["path"], "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            content_type, _ = guess_type(item["path"])
            manifest[item["key"]] = {
                "path": os.path.relpath(item["path"], dir_base).replace("\\", "/"),
                "sha256": sha256,
                "content_type": content_type or "",
                "cache_control": self.cache_control_for_key(item["key"]),
            }
        return manifest

    def upload_files(self, dir: str, bucket, key: str = "") -> SiteFiles:
        """
        Publish the files in a directory to an S3 bucket as one resource.

        Args:
            dir (str): The directory containing the files to upload.
            bucket: The S3 bucket resource to upload files to.
            key (str): The prefix to add to the S3 keys (optional).
        """
        return SiteFiles(
            f"{self._name}-files",
            {
                "bucket": bucket.id,
                "prefix": key,
                "source_dir": os.path.abspath(dir),
                "files": self.build_manifest(dir, key),
                "connection": _connection(),
            },
            opts=pulumi.ResourceOptions(parent=self, depends_on=[bucket]),
        )
