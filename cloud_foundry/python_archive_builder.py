import os
import shutil
import subprocess
import sys
import zipfile

from cloud_foundry.utils.logger import logger
from cloud_foundry.utils.hash_comparator import HashComparator
from cloud_foundry.archive_builder import ArchiveBuilder

log = logger(__name__)

class PythonArchiveBuilder(ArchiveBuilder):
    """
    A class responsible for building Python Lambda function archives with dependencies
    and source code. The class supports caching through hash comparisons to avoid redundant 
    builds and includes functionality to install Python packages in the Lambda package.
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
            sources (dict[str, str]): Dictionary mapping destination file paths to source file paths or inline code.
            requirements (list[str]): List of Python package requirements to be installed.
            working_dir (str): The working directory where intermediate and final outputs are stored.
        """
        self.name = name
        self._sources = sources
        self._requirements = requirements
        self._working_dir = working_dir

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
            # Otherwise, install the requirements, build a new archive, and update the hash
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
        Prepare the staging and library directories where the function source code and dependencies
        will be copied before packaging. Clean any previous contents in the directories.
        """
        # Base directory where Lambda-related files will be stored
        self._base_dir = os.path.join(self._working_dir, f"{self.name}-lambda")
        # Staging directory for the Lambda source code
        self._staging = os.path.join(self._base_dir, "staging")
        # Directory for storing installed Python dependencies
        self._libs = os.path.join(self._base_dir, "libs")
        # Final location of the ZIP archive
        self._location = os.path.join(self._base_dir, f"{self.name}.zip")

        # Clean or create necessary directories
        self.create_clean_folder(self._staging)
        self.create_clean_folder(self._libs)

        # Copy the source code into the staging area
        self.install_sources()
        # Write the requirements file for package installation
        self.write_requirements()

    def build_archive(self):
        """
        Build the ZIP archive by compressing both the 'staging' and 'libs' directories.
        """
        log.info(f"building archive: {self.name}")
        try:
            # Create the archive file
            archive_name = self._location.replace(".zip", "")
            with zipfile.ZipFile(f"{archive_name}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
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

    def install_sources(self):
        """
        Copy the specified source files into the staging directory. Sources can be directories,
        files, or inline content.
        """
        log.info(f"installing resources: {self.name}")
        if not self._sources:
            return
        # log.debug(f"sources: {self._sources}")

        # Copy each source to its corresponding destination
        for destination, source in self._sources.items():
            destination_path = os.path.join(self._staging, destination)
            try:
                if os.path.isdir(source):
                    shutil.copytree(source, destination_path)
                    log.info(f"Folder copied from {source} to {destination_path}")
                elif os.path.isfile(source):
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    shutil.copy2(source, destination_path)
                    log.info(f"File copied from {source} to {destination_path}")
                else:  # Inline content
                    with open(destination_path, "w") as f:
                        f.write(source + "\n")
            except Exception as e:
                log.error(f"Error copying {source} to {destination_path}: {e}")
                raise

    def write_requirements(self):
        """
        Write the Python package requirements into a 'requirements.txt' file in the staging area.
        """
        log.debug("writing requirements")
        if not self._requirements:
            return

        requirements_path = os.path.join(self._staging, "requirements.txt")
        try:
            with open(requirements_path, "w") as f:
                for requirement in self._requirements:
                    f.write(requirement + "\n")
        except Exception as e:
            log.error(f"Error writing requirements to {requirements_path}: {e}")
            raise

    def install_requirements(self):
        """
        Install the required Python packages in the 'libs' directory for packaging into the Lambda archive.
        """
        log.info(f"installing packages {self.name}")
        requirements_file = os.path.join(self._staging, "requirements.txt")
        if not os.path.exists(requirements_file):
            log.warning(f"No requirements file found at {requirements_file}")
            return

        log.info(
            f"Installing packages using: {sys.executable} -m pip "
            + f"install --target {self._libs} --platform manylinux2010_x86_64 "
            + "--implementation cp --only-binary=:all: --upgrade "
            + f"--python-version 3.9 -r {requirements_file}"
        )
        self.clean_folder(self._libs)

        # Install the required packages using pip
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
                    "--platform",
                    "manylinux2010_x86_64",
                    "--implementation",
                    "cp",
                    "--only-binary=:all:",
                    "--upgrade",
                    "--python-version",
                    "3.9",
                    "-r",
                    requirements_file,
                ]
            )
        except subprocess.CalledProcessError as e:
            log.error(f"Error installing requirements: {e}")
            raise

    def create_clean_folder(self, folder_path):
        """
        Create a clean folder by removing existing contents or creating the folder if it doesn't exist.

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
            folder_path (str): Path to the folder from which to remove files and folders.

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
