import os
import shutil
import subprocess
import sys
import zipfile
import urllib
import importlib.resources as pkg_resources

from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.hash_comparator import HashComparator
from cloud_foundry.archive_builder import ArchiveBuilder
import boto3
from urllib.parse import urlparse

log = logger(__name__)


class PythonArchiveBuilder(ArchiveBuilder):
    """
    A class responsible for building Python Lambda function archives with
    dependencies and source code. The class supports caching through hash
    comparisons to avoid redundant builds and includes functionality to
    install Python packages in the Lambda package.
    """

    _hash: str  # Stores the computed hash of the archive
    _location: str  # Stores the location of the generated ZIP archive

    def __init__(
        self,
        name: str,
        *,
        sources: dict[str, str],
        requirements: list[str],
        working_dir: str,
    ):
        """
        Initialize the PythonArchiveBuilder with necessary parameters.

        Args:
            name (str): The name of the archive/Lambda function.
            sources (dict[str, str]): Dictionary mapping destination file
            paths to source file paths or inline code.
            requirements (list[str]): List of Python package requirements to
            be installed.
            working_dir (str): The working directory where intermediate and
            final outputs are stored.
        """
        self.name = name
        self._sources = sources
        self._requirements = requirements
        self._working_dir = working_dir

        # Base directory where Lambda-related files will be stored
        self._base_dir = os.path.join(self._working_dir, f"{self.name}-lambda")
        # Staging directory for the Lambda source code
        self._staging = os.path.join(self._base_dir, "staging")
        # Directory for storing installed Python dependencies
        self._libs = os.path.join(self._base_dir, "libs")
        # Final location of the ZIP archive
        self._location = os.path.join(self._base_dir, f"{self.name}.zip")

        # Prepare staging areas and install sources
        self.prepare()

        # Check for changes using a hash comparison
        hash_comparator = HashComparator()
        new_hash = hash_comparator.hash_folder(self._staging)
        old_hash = hash_comparator.read(self._base_dir)
        log.debug(f"old_hash: {old_hash}, new_hash: {new_hash}")

        if old_hash == new_hash:
            # If the hash matches, use the existing archive
            self._hash = old_hash or ""
        else:
            # Otherwise, install the requirements, build a new archive, and
            # update the hash
            self.install_requirements()
            self.build_archive()
            self._hash = new_hash
            hash_comparator.write(self._hash, self._base_dir)

    def hash(self) -> str:
        """Return the hash of the current archive."""
        return self._hash

    def location(self) -> str:
        """Return the location of the generated ZIP archive."""
        return self._location

    def prepare(self):
        """
        Prepare the staging and library directories where the function source code
        and dependencies will be copied before packaging. Clean any previous
        contents in the directories.
        """
        # Clean or create necessary directories
        self.create_clean_folder(self._staging)
        self.create_clean_folder(self._libs)

        # Copy the source code into the staging area
        self.install_sources(self._staging)
        # Write the requirements file for package installation
        self.write_requirements(self._staging)

    def build_archive(self):
        """
        Build the ZIP archive by compressing both the 'staging' and 'libs' directories.
        """
        log.info(f"building archive: {self.name}")
        try:
            # Create the archive file
            archive_name = self._location.replace(".zip", "")
            with zipfile.ZipFile(
                f"{archive_name}.zip", "w", zipfile.ZIP_DEFLATED
            ) as archive:
                # Include both 'staging' and 'libs' folders in the archive
                for folder in ["staging", "libs"]:
                    folder_path = os.path.join(self._base_dir, folder)
                    if os.path.exists(folder_path):
                        for root, _, files in os.walk(folder_path):
                            for file in files:
                                full_path = os.path.join(root, file)
                                relative_path = os.path.relpath(full_path, folder_path)
                                archive.write(full_path, relative_path)

            log.info("Archive built successfully")
        except Exception as e:
            log.error(f"Error building archive: {e}")
            raise

    def install_sources(self, staging: str):
        """
        Copy the specified source files into the staging directory. Sources
        can be directories, files, or inline content.
        """
        log.info(f"installing resources: {self.name}")
        if not self._sources:
            return
        # log.debug(f"sources: {self._sources}")

        # Copy each source to its corresponding destination
        for destination, source in self._sources.items():
            dest_path = os.path.join(staging, destination)
            # Ensure the staging folder exists
            self._stage_resource(source, dest_path)

    def write_requirements(self, staging: str):
        """
        Write the Python package requirements into a 'requirements.txt' file
        in the staging area.
        """
        log.debug("writing requirements")
        if not self._requirements:
            return

        requirements_path = os.path.join(staging, "requirements.txt")
        try:
            with open(requirements_path, "w") as f:
                for requirement in self._requirements:
                    f.write(requirement + "\n")
        except Exception as e:
            log.error(f"Error writing requirements to {requirements_path}: {e}")
            raise

    def install_requirements(self):
        """
        Install the required Python packages in the 'libs' directory for
        packaging into the Lambda archive.
        """
        log.info(f"installing packages {self.name}")
        requirements_file = os.path.join(self._staging, "requirements.txt")
        if not os.path.exists(requirements_file):
            log.warning(f"No requirements file found at {requirements_file}")
            return

        self.clean_folder(self._libs)

        # Try multiple strategies for installing packages
        install_success = False

        # Strategy 1: Try with manylinux2014 platform wheels (Python 3.12 compatible)
        log.info("Strategy 1: Attempting manylinux2014 platform wheels for Python 3.12")
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--target",
                    self._libs,
                    "--platform",
                    "manylinux2014_x86_64",
                    "--only-binary=:all:",
                    "--implementation",
                    "cp",
                    "--python-version",
                    "3.12",
                    "--upgrade",
                    "-r",
                    requirements_file,
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            install_success = True
            log.info("✓ Successfully installed with manylinux2014 wheels")
        except subprocess.CalledProcessError as e:
            log.info(
                f"✗ Strategy 1 failed: {e.stderr.decode() if e.stderr else 'Unknown error'}"
            )
            self.clean_folder(self._libs)

        # Strategy 2: Try with manylinux_2_17 (broader compatibility for Python 3.12)
        if not install_success:
            log.info("Strategy 2: Attempting manylinux_2_17 platform wheels")
            try:
                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--target",
                        self._libs,
                        "--platform",
                        "manylinux_2_17_x86_64",
                        "--only-binary=:all:",
                        "--implementation",
                        "cp",
                        "--python-version",
                        "3.12",
                        "--upgrade",
                        "-r",
                        requirements_file,
                    ],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
                install_success = True
                log.info("✓ Successfully installed with manylinux_2_17 wheels")
            except subprocess.CalledProcessError as e:
                log.info(
                    f"✗ Strategy 2 failed: {e.stderr.decode() if e.stderr else 'Unknown error'}"
                )
                self.clean_folder(self._libs)

        # Strategy 3: Fall back to regular install (builds from source for current platform)
        if not install_success:
            log.info(
                "Strategy 3: Installing for current platform (may require building from source)"
            )
            log.warning(
                "⚠️  Installing packages for your local platform. "
                "Native extensions (psycopg2, cryptography) may not work in AWS Lambda."
            )
            try:
                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "-v",
                        "--target",
                        self._libs,
                        "--upgrade",
                        "-r",
                        requirements_file,
                    ]
                )
                log.info(
                    "✓ Packages installed (local platform - may need Lambda layers for native deps)"
                )
            except subprocess.CalledProcessError as e:
                log.error(f"✗ All installation strategies failed: {e}")
                raise

    def create_clean_folder(self, folder_path):
        """
        Create a clean folder by removing existing contents or creating the
        folder if it doesn't exist.

        Args:
            folder_path (str): Path to the folder to clean or create.

        Returns:
            None
        """
        if os.path.exists(folder_path):
            self.clean_folder(folder_path)
        else:
            os.makedirs(folder_path)

    def clean_folder(self, folder_path):
        """
        Remove all files and folders from the specified folder.

        Args:
            folder_path (str): Path to the folder from which to remove
            files and folders.

        Returns:
            None
        """
        log.info(f"Cleaning folder: {folder_path}")
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isfile(item_path):
                    os.remove(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            log.info(f"All files and folders removed from {folder_path}")
        except Exception as e:
            log.error(f"Error cleaning folder {folder_path}: {e}")
            raise

    def _get_file_resource(
        self, source_path: str, destination_path: str, default: str = None
    ):
        """
        Copy a file or folder from source_path to destination_path.
        If the source_path does not exist and default is provided, write the default value to the destination.

        Args:
            source_path (str): The path to the source file or folder.
            destination_path (str): The path to copy the file or folder to.
            default (str, optional): Default content to write if source_path does not exist.
        """
        # If source_path doesn't start with '/', treat it as relative to the current working directory
        if not os.path.isabs(source_path):
            source_path = os.path.join(os.getcwd(), source_path)
        if os.path.exists(source_path):
            if os.path.isdir(source_path):
                # Copy directory recursively
                if os.path.exists(destination_path):
                    shutil.rmtree(destination_path)
                shutil.copytree(source_path, destination_path)
                log.info(f"Directory copied from {source_path} to {destination_path}")
            else:
                # Copy single file
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copy2(source_path, destination_path)
                log.info(f"File copied from {source_path} to {destination_path}")
        elif default is not None:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, "w") as f:
                f.write(default)
            log.info(
                f"Default value written to {destination_path} because {source_path} does not exist"
            )
        else:
            log.error(
                f"Source path {source_path} does not exist and no default value provided"
            )
            raise FileNotFoundError(
                f"Source path {source_path} does not exist and no default value provided"
            )
        """
        Copy a file or folder from source_path to destination_path.

        Args:
            source_path (str): The path to the source file or folder.
            destination_path (str): The path to copy the file or folder to.
        """
        # If source_path doesn't start with '/', treat it as relative to the current working directory
        if not os.path.isabs(source_path):
            source_path = os.path.join(os.getcwd(), source_path)
        if os.path.isdir(source_path):
            # Copy directory recursively
            if os.path.exists(destination_path):
                shutil.rmtree(destination_path)
            shutil.copytree(source_path, destination_path)
            log.info(f"Directory copied from {source_path} to {destination_path}")
        else:
            # Copy single file
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.copy2(source_path, destination_path)
            log.info(f"File copied from {source_path} to {destination_path}")

    def _stage_resource(self, source_path: str, destination_path: str):
        """
        Parse a resource URL to extract the protocol, package name, resource path, and resource.

        Args:
            resource_url (str): The resource URL in the format 'pkg://package.module/resource_path'.

        Returns:
            dict: A dictionary containing protocol, pkg_name, resource_path, and resource.
        """

        parsed = urlparse(source_path)

        try:
            if source_path.startswith("s3://"):
                self._get_s3_resource(
                    parsed.netloc, parsed.path.lstrip("/"), destination_path
                )
            elif source_path.startswith("pkg://"):
                self._get_package_resource(
                    parsed.netloc or parsed.path.split("/")[0],
                    "/".join(parsed.path.split("/")[1:]),
                    destination_path,
                )
            elif source_path.startswith("file://"):
                parsed = urllib.parse.urlparse(source_path)
                # Handle relative file URLs (netloc used instead of path)
                if parsed.path:
                    file_path = urllib.parse.unquote(parsed.path)
                elif parsed.netloc:
                    file_path = urllib.parse.unquote(parsed.netloc)
                else:
                    file_path = ""
                self._get_file_resource(file_path, destination_path)
            elif source_path.startswith(("http://", "https://")):
                self._get_network_resource(source_path, destination_path)
            else:  # Inline content
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                with open(destination_path, "w") as f:
                    f.write(source_path + "\n")
                log.info(f"In line source copied to {destination_path}")
        except Exception as e:
            log.error(f"Error copying {source_path} to {destination_path}: {e}")
            raise

    def _get_network_resource(self, url: str, destination_path: str):
        """
        Download a resource from a network URL and save it to the destination path.

        Args:
            url (str): The URL of the resource to download.
            destination_path (str): The path where the downloaded resource will be saved.
        """
        log.info(f"Downloading resource from {url} to {destination_path}")
        try:
            import requests

            response = requests.get(url)
            response.raise_for_status()
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, "wb") as f:
                f.write(response.content)
            log.info(f"Resource downloaded successfully to {destination_path}")
        except Exception as e:
            log.error(f"Error downloading resource from {url}: {e}")
            raise

    def _get_package_resource(
        self, package: str, resource_path: str, destination_path: str
    ):
        """
        Get a file resource from a package and copy it to the destination path.

        Args:
            pkg_name (str): The name of the package.
            resource_path (str): The path to the resource within the package.
            destination_path (str): The path where the resource will be copied.
        """
        try:
            if resource_path.endswith("/"):
                # Import all files from the package folder (resource_path)
                package_files = pkg_resources.files(package).joinpath(resource_path)
                if not package_files.is_dir():
                    raise FileNotFoundError(
                        f"Package folder {resource_path} not found in {package}"
                    )
                for file in package_files.rglob("*"):
                    if file.is_file():
                        rel_path = os.path.relpath(str(file), str(package_files))
                        dest_file = os.path.join(destination_path, rel_path)
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        with file.open("rb") as src, open(dest_file, "wb") as dst:
                            dst.write(src.read())
                log.info(
                    f"Package folder {resource_path} from {package} copied to {destination_path}"
                )
            else:
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                with (
                    pkg_resources.files(package)
                    .joinpath(resource_path)
                    .open("rb") as src,
                    open(destination_path, "wb") as dst,
                ):
                    dst.write(src.read())
                log.info(
                    f"Package resource {resource_path} from {package} copied to {destination_path}"
                )
        except Exception as e:
            log.error(f"Error importing package resource {resource_path}: {e}")
            raise

    def _get_s3_resource(self, bucket: str, key: str, destination_path: str):
        """
        Download a resource from an S3 bucket and save it to the destination path.

        Args:
            bucket (str): The name of the S3 bucket.
            key (str): The key of the resource in the S3 bucket.
            destination_path (str): The path where the downloaded resource will be saved.
        """
        log.info(
            f"Downloading S3 resource from bucket {bucket}, key {key} to {destination_path}"
        )
        try:
            s3 = boto3.client("s3")
            # Check if the key is a folder (ends with '/')
            if key.endswith("/"):
                # List all objects under the prefix
                paginator = s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=bucket, Prefix=key):
                    for obj in page.get("Contents", []):
                        obj_key = obj["Key"]
                        if obj_key.endswith("/"):
                            continue  # Skip folder placeholders
                        rel_path = os.path.relpath(obj_key, key)
                        dest_file = os.path.join(destination_path, rel_path)
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        s3.download_file(bucket, obj_key, dest_file)
                log.info(f"S3 folder downloaded successfully to {destination_path}")
                return
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            s3.download_file(bucket, key, destination_path)
            log.info(f"S3 resource downloaded successfully to {destination_path}")
        except Exception as e:
            log.error(f"Error downloading S3 resource from {bucket}/{key}: {e}")
            raise
