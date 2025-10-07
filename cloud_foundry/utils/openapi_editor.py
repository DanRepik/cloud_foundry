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
        self.merge_spec_item(spec)

    @property
    def yaml(self) -> str:
        return yaml.dump(self.openapi_spec, sort_keys=False)

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

    def get_spec_part(
        self, keys: List[str], create: bool = False
    ) -> Optional[Union[Dict, List, Any]]:
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
        schema_name: str,
        schema_object: Optional[dict] = None,
    ):
        """
        Add an operation to the OpenAPI spec with optional security handling.

        If the schema_object contains x-af-security (role -> permissions mapping),
        roles are converted into OAuth2-style scopes under a single security scheme.
        The operation.security becomes: [{scheme_name: [role1, role2, ...]}]

        Args:
            path (str): API path (e.g. "/items")
            method (str): HTTP method (e.g. "get")
            operation (dict): Operation object
            schema_object (Optional[dict]): Schema carrying x-af-security
            scheme_name (str): Name of the security scheme to apply
        """
        method = method.lower()

        # Only set security if caller did not already provide one.
        if "security" not in operation:
            roles_security = None

            if schema_object and "x-af-security" in schema_object:
                role_map = schema_object["x-af-security"] or {}
                roles = list(role_map.keys())

                # Ensure securitySchemes entry exists / is oauth2 with scopes.
                self._ensure_oauth2_scheme_with_scopes(schema_name, roles, role_map)

                # Convert roles -> scopes for this operation
                roles_security = [{schema_name: roles}] if roles else None

                # Preserve original role permission matrix as an extension
                operation["x-af-security"] = role_map

            if roles_security:
                operation["security"] = roles_security
            else:
                # Fallback to global security (already a list of Security Requirement Objects)
                global_security = self.get_spec_part(["security"])
                if isinstance(global_security, list):
                    # Shallow copy to avoid accidental mutation
                    operation["security"] = list(global_security)

        # Insert / update operation in the paths map
        path_dict = self.get_or_create_spec_part(["paths", path], True)
        path_dict[method] = operation
        return self

    def _ensure_oauth2_scheme_with_scopes(
        self,
        scheme_name: str,
        roles: List[str],
        role_map: Dict[str, Any],
        token_url: str = "https://example.com/oauth2/token",
    ) -> None:
        """
        Ensure an oauth2 security scheme with clientCredentials flow exists and
        contains the provided roles as scopes. If the scheme exists and already
        defines scopes, new ones are merged (idempotent).
        """
        security_schemes = self.get_or_create_spec_part(
            ["components", "securitySchemes"], create=True
        )

        scheme = security_schemes.get(scheme_name)
        if not scheme or scheme.get("type") != "oauth2":
            # (Re)define as oauth2 client credentials flow
            security_schemes[scheme_name] = {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": token_url,
                        "scopes": {},
                    }
                },
                "description": "Auto-generated OAuth2 scheme (roles mapped to scopes).",
            }
            scheme = security_schemes[scheme_name]

        flows = scheme.setdefault("flows", {}).setdefault(
            "clientCredentials",
            {"tokenUrl": token_url, "scopes": {}},
        )
        scopes = flows.setdefault("scopes", {})

        # Merge role scopes with basic description (use permission summary if present)
        for role in roles:
            if role not in scopes:
                perms = role_map.get(role, {})
                # Build a concise description of permissions if dict
                if isinstance(perms, dict):
                    perms_desc = (
                        ", ".join(f"{k}:{v}" for k, v in perms.items()) or "role scope"
                    )
                else:
                    perms_desc = "role scope"
                scopes[role] = f"Access for role '{role}'"

    def remove_attributes_with_pattern(
        self, pattern: str, obj: Optional[Union[Dict, List]] = None
    ) -> None:
        """
        Recursively remove all attributes from the OpenAPI spec that match the
        provided regex pattern.

        Args:
            pattern (str): The regex pattern to match attribute names.
            obj (Optional[Union[Dict, List]]): The object to process. If None,
            starts with the root OpenAPI spec.
        """
        if obj is None:
            obj = self.openapi_spec

        if isinstance(obj, dict):
            keys_to_remove = [key for key in obj if re.match(pattern, key)]
            for key in keys_to_remove:
                del obj[key]
            for value in obj.values():
                self.remove_attributes_with_pattern(pattern, value)
        elif isinstance(obj, list):
            for item in obj:
                self.remove_attributes_with_pattern(pattern, item)
