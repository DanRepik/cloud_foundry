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
    _hash: str
    _location: str

    def __init__(
        self,
        name: str,
        *,
        sources: dict[str, str],
        requirements: list[str],
        working_dir: str,
    ):
        self.name = name
        self._sources = sources
        self._requirements = requirements
        self._working_dir = working_dir

        self.prepare()

        hash_comparator = HashComparator()
        new_hash = hash_comparator.hash_folder(self._staging)
        old_hash = hash_comparator.read(self._base_dir)
        log.debug(f"old_hash: {old_hash}, new_hash: {new_hash}")
        if old_hash == new_hash:
            self._hash = old_hash or ""
        else:
            self.install_requirements()
            self.build_archive()
            self._hash = new_hash
            hash_comparator.write(self._hash, self._base_dir)

    def hash(self) -> str:
        return self._hash

    def location(self) -> str:
        return self._location

    def prepare(self):
        self._base_dir = os.path.join(self._working_dir, f"{self.name}-lambda")
        self._staging = os.path.join(self._base_dir, "staging")
        self._libs = os.path.join(self._base_dir, "libs")
        self._location = os.path.join(self._base_dir, f"{self.name}.zip")

        self.create_clean_folder(self._staging)
        self.create_clean_folder(self._libs)

        self.install_sources()
        self.write_requirements()

    def build_archive(self):
        log.info(f"building archive: {self.name}")
        try:
            # Create the archive file
            archive_name = self._location.replace('.zip', '')
            with zipfile.ZipFile(f"{archive_name}.zip", 'w', zipfile.ZIP_DEFLATED) as archive:
                # Include both 'staging' and 'libs' folders
                for folder in ['staging', 'libs']:
                    folder_path = os.path.join(self._base_dir, folder)
                    log.info(f"folder_path: {folder_path}")
                    if os.path.exists(folder_path):
                        for root, _, files in os.walk(folder_path):
                            for file in files:
                                # Compute the full path of the file
                                full_path = os.path.join(root, file)
                                # Compute the relative path to store in the archive, relative to 'staging' or 'libs'
                                relative_path = os.path.relpath(full_path, folder_path)
                                # Add the file to the archive, using the folder (staging/libs) as a prefix
                                archive_path = os.path.join(folder, relative_path)
                                log.info(f"archive write: {full_path}, archive_path: {relative_path}")
                                archive.write(full_path, relative_path)

            log.info("Archive built successfully")
        except Exception as e:
            log.error(f"Error building archive: {e}")
            raise
            

    def install_sources(self):
        log.info(f"installing resources: {self.name}")
        if not self._sources:
            return
        log.debug(f"sources: {self._sources}")
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
                else:  # inline
                    try:
                        with open(destination_path, "w") as f:
                            f.write(source + "\n")
                    except Exception as e:
                        log.error(
                            "Error writing requirements to "
                            + f"{destination_path}: {e}"
                        )
                        raise
            except Exception as e:
                log.error(f"Error copying {source} to {destination_path}: {e}")
                raise

    def write_requirements(self):
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
        Create a clean folder by removing existing contents or creating
        the folder if it doesn't exist.

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
