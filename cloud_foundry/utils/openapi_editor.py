# openapi_editor.py

import yaml
import json
import os
from typing import Union, Dict, Any, List, Mapping

class OpenAPISpecEditor:
    def __init__(self, spec: Union[str, List[str]]):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[str, List[str]]): A string representing a YAML content, a file path,
                                          or a list of strings containing YAML contents or file paths.
        """
        self.openapi_spec = {}

        if isinstance(spec, list):
            for individual_spec in spec:
                self._merge_spec(individual_spec)
        elif isinstance(spec, str):
            self._merge_spec(spec)
        else:
            raise ValueError(
                "The spec must be a string, a list of strings, or file paths."
            )

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
            if isinstance(value, Mapping) and key in destination:
                destination[key] = self._deep_merge(value, destination.get(key, {}))
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
