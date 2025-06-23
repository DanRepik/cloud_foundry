import pytest
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor


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


def test_add_token_validator(simple_hello_spec):
    editor = AWSOpenAPISpecEditor(simple_hello_spec)
    editor.add_token_validator(
        "myAuth", "myFunc", "arn:aws:lambda:us-east-1:123456789012:function:myFunc"
    )
    assert "myAuth" in editor.openapi_spec["components"]["securitySchemes"]
    scheme = editor.openapi_spec["components"]["securitySchemes"]["myAuth"]
    assert scheme["type"] == "apiKey"
    assert scheme["x-amazon-apigateway-authorizer"]["type"] == "token"


def test_add_user_pool_validator(simple_hello_spec):
    editor = AWSOpenAPISpecEditor(simple_hello_spec)
    arns = ["arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_ABC123"]
    editor.add_user_pool_validator("cognitoAuth", arns)
    scheme = editor.openapi_spec["components"]["securitySchemes"]["cognitoAuth"]
    assert scheme["x-amazon-apigateway-authorizer"]["providerARNs"] == arns


def test_add_integration(simple_hello_spec):
    editor = AWSOpenAPISpecEditor(simple_hello_spec)
    editor.openapi_spec["paths"]["/test"] = {"get": {}}
    editor.add_integration(
        "/hello",
        "get",
        "myFunc",
        "arn:aws:lambda:us-east-1:123456789012:function:myFunc",
    )
    op = editor.openapi_spec["paths"]["/hello"]["get"]
    assert op["x-function-name"] == "myFunc"
    assert op["x-amazon-apigateway-integration"]["type"] == "aws_proxy"


def test_correct_schema_names():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                "My-Schema_1": {"type": "object"},
                "Another.Schema": {"type": "object"},
            }
        },
    }
    editor = AWSOpenAPISpecEditor(spec)
    editor.correct_schema_names()
    schemas = editor.openapi_spec["components"]["schemas"]
    assert "MySchema" in schemas
    assert "AnotherSchema" in schemas


def test_collect_function_names():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/foo": {
                "get": {"x-function-name": "fooFunc"},
                "post": {"x-function-name": "barFunc"},
            }
        },
        "components": {"securitySchemes": {"auth1": {"x-function-name": "bazFunc"}}},
    }
    editor = AWSOpenAPISpecEditor(spec)
    names = editor.collect_function_names()
    assert set(names) == {"fooFunc", "barFunc", "bazFunc"}


def test_prefix_paths():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {"/foo": {}, "/bar": {}},
    }
    editor = AWSOpenAPISpecEditor(spec)
    editor.prefix_paths("/v1")
    assert "/v1/foo" in editor.openapi_spec["paths"]
    assert "/v1/bar" in editor.openapi_spec["paths"]


def test_remove_unintegrated_operations():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/foo": {
                "get": {"x-amazon-apigateway-integration": {}},
                "post": {},
            },
            "/bar": {
                "get": {},
            },
        },
    }
    editor = AWSOpenAPISpecEditor(spec)
    editor.remove_unintegrated_operations()
    assert "get" in editor.openapi_spec["paths"]["/foo"]
    assert "post" not in editor.openapi_spec["paths"]["/foo"]
    assert "/bar" not in editor.openapi_spec["paths"]
