"""
Regression test: AWSOpenAPISpecEditor.add_integration() must fail loudly
when the target path/method isn't declared in the base OpenAPI spec.

Previously, get_or_create_spec_part(..., create=True) both created an
empty {} at the target path/method as a side effect AND returned that
empty (falsy) dict, so `if not operation: return` silently no-op'd -
dropping the Lambda integration with only a warning log, and leaving a
dangling empty operation stub behind. A deploy would proceed with a
route that has no integration wired to it at all.
"""

import pytest

from cloud_foundry.utils.aws_openapi_editor import AWSOpenAPISpecEditor


def _simple_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/hello": {
                "get": {
                    "summary": "Say hello",
                    "responses": {"200": {"description": "A greeting"}},
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
    }


@pytest.mark.unit
def test_add_integration_raises_for_undeclared_route():
    editor = AWSOpenAPISpecEditor(_simple_spec())

    with pytest.raises(ValueError, match="not declared in the OpenAPI spec"):
        editor.add_integration(
            "/does-not-exist",
            "get",
            "myFunc",
            "arn:aws:lambda:us-east-1:123456789012:function:myFunc",
        )

    # And no dangling stub should have been left behind in the spec.
    assert "/does-not-exist" not in editor.openapi_spec["paths"]


@pytest.mark.unit
def test_add_integration_still_works_for_declared_route():
    editor = AWSOpenAPISpecEditor(_simple_spec())

    editor.add_integration(
        "/hello",
        "get",
        "myFunc",
        "arn:aws:lambda:us-east-1:123456789012:function:myFunc",
    )

    op = editor.openapi_spec["paths"]["/hello"]["get"]
    assert op["x-function-name"] == "myFunc"
    assert op["x-amazon-apigateway-integration"]["type"] == "aws_proxy"
