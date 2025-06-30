import pytest
import boto3
import json
import uuid
from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor
from tests.automation_helpers import deploy_stack_no_teardown

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

def s3_deployment():
    def pulumi_program():
        import pulumi
        from cloud_foundry import site_bucket
        import uuid
        bucket = site_bucket(
            name="test-bucket")
        pulumi.export("bucket_name", bucket.bucket_name) 

    return pulumi_program

@pytest.fixture(scope="module")
def simple_s3_stack():
    yield from deploy_stack_no_teardown("cf-test", "simple-s3", s3_deployment())


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

def test_retrieve_file_from_s3(simple_s3_stack, simple_hello_spec):
    # Get the bucket name from the Pulumi stack outputs
    context, outputs = simple_s3_stack
    print(f"outputs: {outputs}")
    bucket_name = outputs["bucket_name"].value

    # Create the S3 client
    s3 = boto3.client("s3")

    # Upload a test file to the bucket
    test_key = f"test-folder/test-file-{uuid.uuid4().hex}.txt"
    test_content = json.dumps(simple_hello_spec)
    s3.put_object(Bucket=bucket_name, Key=test_key, Body=test_content)

    editor = AWSOpenAPISpecEditor(f"s3://{bucket_name}/{test_key}")
    print(f"editor: {editor.to_yaml}")

def test_list_folder_from_s3(simple_s3_stack):
    context, outputs = simple_s3_stack
    bucket_name = outputs["bucket_name"].value
    s3 = boto3.client("s3")

    # Upload multiple files to a folder
    folder = f"folder-{uuid.uuid4().hex}/"
    keys = [f"{folder}file1.txt", f"{folder}file2.txt", f"{folder}file3.txt"]
    for key in keys:
        s3.put_object(Bucket=bucket_name, Key=key, Body=b"data")

    # List objects in the folder
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=folder)
    returned_keys = [obj["Key"] for obj in response.get("Contents", [])]
    for key in keys:
        assert key in returned_keys