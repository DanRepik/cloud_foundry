import os
import json
import tempfile
import pytest
import yaml
from cloud_foundry.utils.openapi_editor import OpenAPISpecEditor
import io


@pytest.fixture
def simple_hello_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test Hello API", "version": "1.0.0"},
        "paths": {
            "/hello": {
                "get": {
                    "summary": "Say hello",
                    "responses": {
                        "200": {
                            "description": "A greeting",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
    }


@pytest.fixture
def simple_goodbye_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test Goodbye API", "version": "1.0.0"},
        "paths": {
            "/goodbye": {
                "get": {
                    "summary": "Say goodbye",
                    "responses": {
                        "200": {
                            "description": "A farewell message",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"farewell": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
    }


def test_init_with_yaml_str(simple_hello_spec):
    yaml_str = io.StringIO()
    yaml.dump(simple_hello_spec, yaml_str)
    yaml_str.seek(0)
    editor = OpenAPISpecEditor(yaml_str.getvalue())
    assert editor.openapi_spec["info"]["title"] == "Test Hello API"


def test_init_with_json_str(simple_hello_spec):
    editor = OpenAPISpecEditor(json.dumps(simple_hello_spec))
    assert editor.openapi_spec["info"]["title"] == "Test Hello API"


def test_init_with_dict(simple_hello_spec):
    print(type(simple_hello_spec))
    editor = OpenAPISpecEditor(simple_hello_spec)
    assert editor.openapi_spec["info"]["title"] == "Test Hello API"


def test_init_with_yaml_file(simple_hello_spec):
    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f:
        yaml.dump(simple_hello_spec, f)
        f.flush()
        editor = OpenAPISpecEditor(f.name)
        assert editor.openapi_spec["info"]["title"] == "Test Hello API"
    os.remove(f.name)


def test_init_with_list_of_files(simple_hello_spec, simple_goodbye_spec):
    with (
        tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f1,
        tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as f2,
    ):
        yaml.dump(simple_hello_spec, f1)
        yaml.dump(simple_goodbye_spec, f2)
        f1.flush()
        f2.flush()
        editor = OpenAPISpecEditor([f1.name, f2.name])
        # Should load both files as strings in resolved_spec
        merged_spec = editor.openapi_spec
        assert editor.openapi_spec["info"]["title"] == "Test Goodbye API"
        assert merged_spec["paths"]["/hello"]["get"]["summary"] == "Say hello"
        assert merged_spec["paths"]["/goodbye"]["get"]["summary"] == "Say goodbye"
    os.remove(f1.name)
    os.remove(f2.name)


def test_init_with_folder_of_files(simple_hello_spec, simple_goodbye_spec):
    with tempfile.TemporaryDirectory() as temp_dir:
        file1 = os.path.join(temp_dir, "spec1.yaml")
        file2 = os.path.join(temp_dir, "spec2.yaml")
        with open(file1, "w") as f1, open(file2, "w") as f2:
            yaml.dump(simple_hello_spec, f1)
            yaml.dump(simple_goodbye_spec, f2)
        editor = OpenAPISpecEditor(temp_dir)
        merged_spec = editor.openapi_spec
        assert merged_spec["paths"]["/hello"]["get"]["summary"] == "Say hello"
        assert merged_spec["paths"]["/goodbye"]["get"]["summary"] == "Say goodbye"


def test_merge_spec_item_with_invalid_string():
    invalid_yaml = "foo: bar: baz"  # Invalid YAML: mapping values are not allowed here
    try:
        OpenAPISpecEditor(invalid_yaml)
        raise AssertionError("Expected ValueError for invalid YAML string")
    except ValueError as e:
        print(f"Expected error: {e}")
        assert "Failed to parse string as YAML/JSON" in str(e)


def test_get_or_create_spec_part_create():
    editor = OpenAPISpecEditor()
    part = editor.get_or_create_spec_part(["paths", "/foo"], create=True)
    assert isinstance(part, dict)
    assert "/foo" in editor.openapi_spec["paths"]


def test_get_spec_part_missing():
    editor = OpenAPISpecEditor()
    assert editor.get_spec_part(["not", "exist"]) is None


def test_get_operation_and_add_operation():
    editor = OpenAPISpecEditor()
    op = {"summary": "Test operation"}
    editor.add_operation(
        path="/foo", method="get", schema_name="schema_name", operation=op
    )
    result = editor.get_operation("/foo", "get")
    assert result["summary"] == "Test operation"


def test_add_operation_uses_global_security():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
        "security": [{"globalAuth": []}],
    }
    editor = OpenAPISpecEditor(spec)
    op = {"summary": "Global security"}
    editor.add_operation(
        path="/glob", method="put", schema_name="schema_name", operation=op
    )
    result = editor.get_operation("/glob", "put")
    assert "security" in result
    assert result["security"] == [{"globalAuth": []}]


def test_remove_attributes_with_pattern():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/foo": {
                "get": {"x-remove-me": 1, "summary": "keep"},
                "post": {"summary": "keep2"},
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
        "x-top": "remove",
    }
    editor = OpenAPISpecEditor(spec)
    editor.remove_attributes_with_pattern(r"^x-")
    assert "x-top" not in editor.openapi_spec
    assert "x-remove-me" not in editor.openapi_spec["paths"]["/foo"]["get"]
    assert "summary" in editor.openapi_spec["paths"]["/foo"]["get"]


def test_to_yaml_and_yaml_property():
    editor = OpenAPISpecEditor()
    yml = editor.yaml
    print(f"YAML output:\n{yml}")
    assert "openapi: 3.0.3" in yml
    assert editor.yaml == yml
