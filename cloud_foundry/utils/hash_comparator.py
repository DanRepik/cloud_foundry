import hashlib
import os
import re
from cloud_foundry.utils.logger import logger

log = logger(__name__)

class HashComparator:
    def __init__(self, hash_algorithm="sha256"):
        self.hash_algorithm = hash_algorithm

    def check_folder(self, hash_file: str, hash_dir: str):
        """Compares the stored hash with the current hash of the directory."""
        old_hash = self.read(hash_file)
        log.info(f"old_hash: {old_hash}")
        if old_hash is None:
            return False

        new_hash = self.hash_folder(hash_dir)
        log.info(f"new_hash: {new_hash}")
        return self.compare(old_hash, new_hash)

    def hash_file(self, file_path):
        """Efficiently calculate the hash value of a file using streaming."""
        hasher = hashlib.new(self.hash_algorithm)
        with open(file_path, "rb") as f:
            while chunk := f.read(4096):
                hasher.update(chunk)
        return hasher.hexdigest()

    def hash_folder(self, folder_path, include_regex=None, exclude_regex=None, include_metadata=False):
        """
        Calculates a hash of the folder's contents (including its files and subfolders).

        Args:
            folder_path (str): Path to the folder to hash.
            include_regex (str): Optional regex to include files.
            exclude_regex (str): Optional regex to exclude files.
            include_metadata (bool): If True, include file metadata (e.g., modification time) in the hash.
        """
        hasher = hashlib.new(self.hash_algorithm)
        include_pattern = re.compile(include_regex) if include_regex else None
        exclude_pattern = re.compile(exclude_regex) if exclude_regex else None

        for root, dirs, files in os.walk(folder_path):
            # Sort directories and files to ensure deterministic hash
            dirs.sort()
            files.sort()

            for file in files:
                file_path = os.path.join(root, file)

                # Check if the file should be included or excluded
                if include_pattern and not include_pattern.match(file):
                    continue
                if exclude_pattern and exclude_pattern.match(file):
                    continue

                # Update the folder hash with the file path and file content
                relative_path = os.path.relpath(file_path, folder_path)
                hasher.update(relative_path.encode())  # Update the hash with the file path
                
                if include_metadata:
                    # Include metadata such as file modification time, size, and permissions
                    stat = os.stat(file_path)
                    hasher.update(str(stat.st_mtime).encode())  # Modification time
                    hasher.update(str(stat.st_size).encode())   # File size
                    hasher.update(str(stat.st_mode).encode())   # File permissions
                
                # Hash file content and update the folder hash
                with open(file_path, "rb") as f:
                    while chunk := f.read(4096):
                        hasher.update(chunk)

        return hasher.hexdigest()

    def read(self, file_path):
        """Read the hash value from a file (expected to be stored in a `.hash` file)."""
        log.debug(f"reading hash: {file_path}")
        hash_file = os.path.join(file_path, ".hash")

        if not os.path.exists(hash_file):
            return None

        try:
            with open(hash_file, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            log.debug(f"hash file not found: {hash_file}")
            return None

    def write(self, hash_value, file_path):
        """Write the hash value to a `.hash` file in the specified directory."""
        log.debug(f"writing hash: {file_path}")
        with open(os.path.join(file_path, ".hash"), "w") as f:
            f.write(hash_value)

    def compare(self, hash_value1, hash_value2):
        """Compares two hash values."""
        return hash_value1 == hash_value2
