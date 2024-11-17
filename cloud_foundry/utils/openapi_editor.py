# openapi_editor.py

import yaml
import json
import os
import re
from typing import Union, Dict, Any, List, Mapping, Optional
from cloud_foundry.utils.logger import logger

log = logger(__name__)

class OpenAPISpecEditor:
    def __init__(self, spec: Union[Dict[str, Any], str, List[str]]):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[str, List[str]]): A string representing a YAML content, a file path,
                                          or a list of strings containing YAML contents or file paths.
        """
        self.openapi_spec = {}

        if isinstance(spec, dict):
            self.openapi_spec = spec
        elif isinstance(spec, list):
            for individual_spec in spec:
                self._merge_spec(individual_spec)
        elif isinstance(spec, str):
            self._merge_spec(spec)
        else:
            raise ValueError(
                "The spec must be a string, a list of strings, or file paths."
            )
        # log.info(f"merged spec: {self.to_yaml()}")

    def _merge_spec(self, spec: str):
        """Merge a single OpenAPI spec into the current one."""
        # Check if the string is a file path to a YAML file
        if os.path.isfile(spec) and (spec.endswith(".yaml") or spec.endswith(".yml")):
            self.file_name = spec
            new_spec_dict = self._load_openapi_spec()
        else:
            # Assume the string is YAML content and parse it
            new_spec_dict = yaml.safe_load(spec)

        # Deep merge the new spec into the current spec
        self.openapi_spec = self._deep_merge(new_spec_dict, self.openapi_spec)

    def _load_openapi_spec(self) -> Dict:
        """Load the OpenAPI spec from a YAML or JSON file."""
        with open(self.file_name, "r") as file:
            if self.file_name.endswith(".yaml") or self.file_name.endswith(".yml"):
                return yaml.safe_load(file)
            elif self.file_name.endswith(".json"):
                return json.load(file)
            else:
                raise ValueError("Unsupported file format. Use .json, .yaml, or .yml.")

    def _deep_merge(
        self, source: Dict[Any, Any], destination: Dict[Any, Any]
    ) -> Dict[Any, Any]:
        """
        Deep merge two dictionaries. The source dictionary's values will overwrite
        those in the destination in case of conflicts.

        Args:
            source (Dict[Any, Any]): The dictionary to merge into the destination.
            destination (Dict[Any, Any]): The dictionary into which source will be merged.

        Returns:
            Dict[Any, Any]: The merged dictionary.
        """
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(destination.get(key), Mapping):
                destination[key] = self._deep_merge(value, destination.get(key, {}))
            elif isinstance(value, list):
                # Handle lists by replacing the value if the list in source is empty, otherwise merge lists
                if not value:
                    destination[key] = value  # Override with empty list
                elif key in destination and isinstance(destination[key], list):
                    # Merge non-empty lists if both are lists
                    destination[key].extend(value)
                else:
                    destination[key] = value
            else:
                destination[key] = value
        return destination

    def get_or_create_spec_part(self, keys: List[str], create: bool = False) -> Any:
        """
        Get a part of the OpenAPI spec based on a list of keys. Optionally create parts if they do not exist.

        Args:
            keys (List[str]): A list of keys representing the path to the part of the spec.
            create (bool): If True, create the parts if they do not exist.

        Returns:
            Any: The nested dictionary or list element based on the keys provided.
        """
        part = self.openapi_spec
        for key in keys:
            if create and key not in part:
                part[key] = {}
            part = part.get(key)
            if part is None:
                raise KeyError(f"Part '{'.'.join(keys)}' does not exist in the spec.")
        return part

    def get_spec_part(self, keys: List[str], create: bool = False) -> Optional[Any]:
        try:
            return self.get_or_create_spec_part(keys, False)
        except KeyError:
            return None

    def get_operation(self, path: str, method: str) -> Dict:
        """Retrieve a specific operation (method and path) from the OpenAPI spec."""
        method = (
            method.lower()
        )  # Ensure method is lowercase, as OpenAPI uses lowercase for methods

        # Check if the path exists in the spec
        if path not in self.openapi_spec.get("paths", {}):
            raise ValueError(f"Path '{path}' not found in OpenAPI spec.")

        # Check if the method exists for the specified path
        operations = self.openapi_spec["paths"][path]
        if method not in operations:
            raise ValueError(
                f"Method '{method}' not found for path '{path}' in OpenAPI spec."
            )

        # Return the operation details
        return operations[method]

    def add_operation(self, path: str, method: str, operation: dict, schema_object: Optional[dict] = None):
        """
        Add an operation to the OpenAPI spec with optional security handling.

        Args:
            path (str): The API path.
            method (str): The HTTP method.
            operation (dict): The operation definition.
            schema_object (Optional[dict]): The schema object to check for `x-af-security`.
        """

        # Check for `x-af-security` in the schema
        if schema_object and "x-af-security" in schema_object:
            operation["security"] = [{key: []} for key in schema_object["x-af-security"].keys()]
        else:
            # Use global security if `x-af-security` is not defined
            global_security = self.get_spec_part(["security"])
            if global_security:
                operation["security"] = global_security

        # Retrieve the operation
        path = self.get_or_create_spec_part(["paths", path], True)
        path[method] = operation

        return self

    def add_operation_attribute(
        self, path: str, method: str, attribute: str, value
    ) -> "OpenAPISpecEditor":
        """
        Add an attribute to a specific operation and return self for chaining.

        Args:
            path (str): The API path (e.g., "/token").
            method (str): The HTTP method (e.g., "post").
            attribute (str): The name of the attribute to add.
            value: The value of the attribute to add.

        Returns:
            OpenAPISpecEditor: Returns the instance for chaining.
        """
        # Retrieve the operation
        operation = self.get_operation(path, method)

        # Add or update the attribute in the operation
        operation[attribute] = value

        # Return self to allow method chaining
        return self

    def remove_attributes_by_pattern(self, pattern: str) -> None:
        """
        Remove all attributes in the OpenAPI specification that match the provided regex pattern.

        Args:
            pattern (str): A regex pattern to match keys in the OpenAPI spec.

        Returns:
            None
        """
        compiled_pattern = re.compile(pattern)

        def remove_matching_keys(data: Union[Dict, List]) -> Union[Dict, List]:
            """Recursively remove keys matching the regex pattern."""
            if isinstance(data, dict):
                return {
                    key: remove_matching_keys(value)
                    for key, value in data.items()
                    if not compiled_pattern.match(key)
                }
            elif isinstance(data, list):
                return [remove_matching_keys(item) for item in data]
            return data

        self.openapi_spec = remove_matching_keys(self.openapi_spec)
        log.info(f"Attributes matching '{pattern}' have been removed from the spec.")


    def merge_with(self, new_spec: Union[Dict, str]) -> "OpenAPISpecEditor":
        """
        Merge another OpenAPI specification with the current one, with the new spec winning conflicts.

        Args:
            new_spec (Union[Dict, str]): The new OpenAPI specification to merge in. Can be a dictionary
                                         or a string representing YAML content or a file path.

        Returns:
            OpenAPISpecEditor: Returns the instance for chaining.
        """
        if isinstance(new_spec, dict):
            new_spec_dict = new_spec
        elif isinstance(new_spec, str):
            # Check if the string is a file path to a YAML file
            if os.path.isfile(new_spec) and (
                new_spec.endswith(".yaml") or new_spec.endswith(".yml")
            ):
                with open(new_spec, "r") as file:
                    new_spec_dict = yaml.safe_load(file)
            else:
                # Assume the string is YAML content and parse it
                new_spec_dict = yaml.safe_load(new_spec)
        else:
            raise ValueError(
                "The new_spec must be a dictionary or a valid YAML string or file path."
            )

        # Deep merge the new spec into the current spec, with new_spec taking precedence
        self.openapi_spec = self._deep_merge(new_spec_dict, self.openapi_spec)

        return self

    def to_yaml(self) -> str:
        """Return the OpenAPI specification as a YAML-formatted string."""
        return yaml.dump(self.openapi_spec)
