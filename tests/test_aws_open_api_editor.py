import pytest
import boto3
import json
import uuid
import yaml

import pulumi
import pulumi_aws as aws

from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor
from cloud_foundry import site_bucket

from fixture_foundry import deploy, localstack, container_network


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
                                        "properties": {
                                            "message": {"type": "string"}
                                        },  # noqa: E501
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


# Ensure boto3 inside AWSOpenAPISpecEditor talks to LocalStack
@pytest.fixture(autouse=True)
def boto3_uses_localstack(monkeypatch, localstack):
    # Prefer service-specific endpoint var if supported; fall back to global
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", localstack["endpoint_url"])
    # botocore >= 1.31 supports AWS_ENDPOINT_URL
    monkeypatch.setenv("AWS_ENDPOINT_URL", localstack["endpoint_url"])  # noqa: E501
    monkeypatch.setenv("AWS_DEFAULT_REGION", localstack["region"])
    # Dummy creds for LocalStack
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    # Avoid metadata lookups slowing tests
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    # Path-style S3 addressing is safest across LocalStack setups
    monkeypatch.setenv("AWS_S3_ADDRESSING_STYLE", "path")


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
                                        "properties": {
                                            "farewell": {"type": "string"}
                                        },  # noqa: E501
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
        bucket = site_bucket(
            name="test-bucket",
            bucket_name=f"test-bucket-{uuid.uuid4()}",
        )

        # If site_bucket returns a component whose bucket_name is NOT an
        # Output, force the dependency using depends_on.
        aws.s3.BucketObject(
            "test-object",
            bucket=bucket.bucket_name,
            key="hello.json",
            content=json.dumps(simple_hello_spec()),
            opts=pulumi.ResourceOptions(depends_on=[bucket]),
        )

        folder_key = "test-folder/"
        aws.s3.BucketObject(
            "test-hello-object",
            bucket=bucket.bucket_name,
            key=f"{folder_key}hello.yaml",
            content=yaml.dump(simple_hello_spec()),
            opts=pulumi.ResourceOptions(depends_on=[bucket]),
        )

        aws.s3.BucketObject(
            "test-goodbye-object",
            bucket=bucket.bucket_name,
            key=f"{folder_key}goodbye.yaml",
            content=yaml.dump(simple_goodbye_spec()),
            opts=pulumi.ResourceOptions(depends_on=[bucket]),
        )

        pulumi.export("bucket_name", bucket.bucket_name)

    return pulumi_program


@pytest.fixture(scope="module")
def simple_s3_stack(request, localstack):

    teardown = request.config.getoption("--teardown").lower() == "true"
    with deploy(
        "cf-test",
        "simple-s3",
        s3_deployment(),
        localstack=localstack,
        teardown=teardown,
    ) as outputs:
        yield outputs


@pytest.fixture
def s3_client(localstack):
    return boto3.client(
        "s3",
        region_name=localstack["region"],
        endpoint_url=localstack["endpoint_url"],
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_add_token_validator():
    editor = AWSOpenAPISpecEditor(simple_hello_spec())
    editor.add_token_validator(
        "myAuth",
        "myFunc",
        "arn:aws:lambda:us-east-1:123456789012:function:myFunc",  # noqa: E501
    )
    assert "myAuth" in editor.openapi_spec["components"]["securitySchemes"]
    scheme = editor.openapi_spec["components"]["securitySchemes"]["myAuth"]
    assert scheme["type"] == "apiKey"
    assert scheme["x-amazon-apigateway-authorizer"]["type"] == "token"


def test_add_user_pool_validator():
    editor = AWSOpenAPISpecEditor(simple_hello_spec())
    arns = [
        "arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_ABC123"  # noqa: E501
    ]
    editor.add_user_pool_validator("cognitoAuth", arns)
    scheme = editor.openapi_spec["components"]["securitySchemes"]["cognitoAuth"]
    assert scheme["x-amazon-apigateway-authorizer"]["providerARNs"] == arns


def test_add_integration():
    editor = AWSOpenAPISpecEditor(simple_hello_spec())
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


def test_retrieve_file_from_s3(simple_s3_stack):
    # Get the bucket name from the Pulumi stack outputs
    outputs = simple_s3_stack
    print(f"outputs: {outputs}")
    bucket_name = outputs["bucket_name"]

    editor = AWSOpenAPISpecEditor(f"s3://{bucket_name}/hello.json")
    print(f"editor: {editor.yaml}")
    assert editor.openapi_spec["paths"]["/hello"]["get"] is not None


def test_retrieve_folder_from_s3(simple_s3_stack):
    # Get the bucket name from the Pulumi stack outputs
    outputs = simple_s3_stack
    print(f"outputs: {outputs}")
    bucket_name = outputs["bucket_name"]

    editor = AWSOpenAPISpecEditor(f"s3://{bucket_name}/test-folder/")
    print(f"editor: {editor.yaml}")
    assert editor.openapi_spec["paths"]["/hello"]["get"] is not None
    assert editor.openapi_spec["paths"]["/goodbye"]["get"] is not None
