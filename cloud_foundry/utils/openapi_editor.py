# openapi_editor.py

import yaml
import json
import os
import re
from typing import Union, Dict, Any, List, Mapping, Optional
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class OpenAPISpecEditor:
    def __init__(self, spec: Optional[Union[Dict[str, Any], str, List[str]]] = None):
        """
        Initialize the class by loading the OpenAPI specification.

        Args:
            spec (Union[str, List[str]]): A string representing a YAML content,
            a file path, or a list of strings containing YAML contents or file paths.
        """
        self.openapi_spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "API",
                "version": "1.0.0",
                "description": "Generated OpenAPI Spec",
            },
            "paths": {},
            "components": {"schemas": {}, "securitySchemes": {}},
        }
        self._yaml = None
        self.merge_spec_item(spec)

    def _deep_merge(
        self, source: Dict[Any, Any], destination: Dict[Any, Any] = None
    ) -> Dict[Any, Any]:
        """
        Deep merge two dictionaries. The source dictionary's values will overwrite
        those in the destination in case of conflicts.

        Args:
            source (Dict[Any, Any]): The dictionary to merge into the destination.
            destination (Dict[Any, Any]): The dictionary into which source will be
            merged.

        Returns:
            Dict[Any, Any]: The merged dictionary.
        """
        if destination is None:
            destination = self.openapi_spec

        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(destination.get(key), Mapping):
                destination[key] = self._deep_merge(value, destination.get(key, {}))
            elif isinstance(value, list):
                # Handle lists by replacing the value if the list in source is empty,
                # otherwise merge lists
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

    def merge_spec_item(self, item: Union[str, list[str]]) -> Dict[str, Any]:
        if not item:
            return
        if isinstance(item, dict):
            self._deep_merge(item)
        elif isinstance(item, list):
            for elem in item:
                self.merge_spec_item(elem)
        elif os.path.isdir(item):
            # Import all YAML/YML/JSON files from the folder in alphabetical order
            files = sorted(
                [
                    f
                    for f in os.listdir(item)
                    if f.lower().endswith((".yaml", ".yml", ".json"))
                ]
            )
            # Sort the files before processing
            files = sorted(files)
            for fname in files:
                self.merge_spec_item(os.path.join(item, fname))
        elif os.path.isfile(item) and item.lower().endswith((".yaml", ".yml", ".json")):
            # Import a single YAML/YML/JSON file
            with open(item, "r", encoding="utf-8") as f:
                self.merge_spec_item(f.read())
        else:
            # If item is a string, try to parse as YAML or JSON
            try:
                # Try YAML first (YAML is a superset of JSON)
                data = yaml.safe_load(item)
                if isinstance(data, dict):
                    self._deep_merge(data)
                else:
                    self._deep_merge(json.load(item))
            except Exception as e:
                raise ValueError(f"Failed to parse string as YAML/JSON: {e}")

    def get_or_create_spec_part(self, keys: List[str], create: bool = False) -> Any:
        """
        Get a part of the OpenAPI spec based on a list of keys. Optionally create
        parts if they do not exist.

        Args:
            keys (List[str]): A list of keys representing the path to the part of the
            spec.
            create (bool): If True, create the parts if they do not exist.

        Returns:
            Any: The nested dictionary or list element based on the keys provided.
        """
        part = self.openapi_spec
        for key in keys:
            if create and key not in part:
                part[key] = {}
            if key in part:
                part = part[key]
            else:
                raise KeyError(f"Part '{'.'.join(keys)}' does not exist in the spec.")
        return part

    def get_spec_part(self, keys: List[str], create: bool = False) -> Optional[Union[Dict, List, Any]]:
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

    def add_operation(
        self,
        path: str,
        method: str,
        operation: dict,
        schema_object: Optional[dict] = None,
    ):
        """
        Add an operation to the OpenAPI spec with optional security handling.

        Args:
            path (str): The API path.
            method (str): The HTTP method.
            operation (dict): The operation definition.
            schema_object (Optional[dict]): The schema object to check for
            `x-af-security`.
        """

        # Check for `x-af-security` in the schema
        if schema_object and "x-af-security" in schema_object:
            operation["security"] = [
                {key: []} for key in schema_object["x-af-security"].keys()
            ]
        else:
            # Use global security if `x-af-security` is not defined
            global_security = self.get_spec_part(["security"])
            if global_security:
                operation["security"] = [global_security]

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
        Remove all attributes in the OpenAPI specification that match the
        provided regex pattern.

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

    def prune(self, keys: List[str]) -> Any:
        """
        Remove the attribute specified by the path list from the OpenAPI spec and return the pruned element.

        Args:
            keys (List[str]): A list of keys representing the path to the attribute to remove.

        Returns:
            Any: The pruned element if found and removed, otherwise None.
        """
        if not keys:
            return None
        part = self.openapi_spec
        for key in keys[:-1]:
            if key in part and isinstance(part[key], dict):
                part = part[key]
            else:
                log.warning(f"Path '{'.'.join(keys)}' does not exist in the spec.")
                return None
        removed = part.pop(keys[-1], None)
        if removed is not None:
            log.info(f"Attribute '{'.'.join(keys)}' has been pruned from the spec.")
        else:
            log.warning(f"Attribute '{'.'.join(keys)}' not found for pruning.")
        return removed
        """
        Remove the attribute specified by the path list from the OpenAPI spec.

        Args:
            keys (List[str]): A list of keys representing the path to the attribute to remove.

        Returns:
            None
        """
        if not keys:
            return
        part = self.openapi_spec
        for key in keys[:-1]:
            if key in part and isinstance(part[key], dict):
                part = part[key]
            else:
                log.warning(f"Path '{'.'.join(keys)}' does not exist in the spec.")
                return
        removed = part.pop(keys[-1], None)
        if removed is not None:
            log.info(f"Attribute '{'.'.join(keys)}' has been pruned from the spec.")
        else:
            log.warning(f"Attribute '{'.'.join(keys)}' not found for pruning.")

    def set(self, keys: List[str], value: Any) -> "OpenAPISpecEditor":
        """
        Set a value in the OpenAPI spec at the specified path.

        Args:
            keys (List[str]): A list of keys representing the path to set the value.
            value (Any): The value to set at the specified path.

        Returns:
            OpenAPISpecEditor: Returns self for method chaining.
        """
        part = self.openapi_spec
        for key in keys[:-1]:
            if key not in part or not isinstance(part[key], dict):
                part[key] = {}
            part = part[key]
        part[keys[-1]] = value
        return self 
    
    def to_yaml(self) -> str:
        """Return the OpenAPI specification as a YAML-formatted string."""
        if self.openapi_spec:
            self._yaml = yaml.dump(self.openapi_spec)
        else:
            log.warning("OpenAPI spec is empty, returning empty YAML.")
            self._yaml = ""
        return self._yaml

    @property
    def yaml(self) -> str:
        return self.to_yaml()

    @property
    def json(self) -> str:
        return json.dumps(self.openapi_spec, indent=2)
