"""
Regression tests for AWSOpenAPISpecEditor.cors_origins().

Previously, the Access-Control-Allow-Origin response header was built as
f"'{','.join(cors_origins)}'" - a single comma-joined string. Per the
Fetch/CORS spec, that header must be a single origin (or '*'); browsers
reject the comma-joined form outright, so any RestAPI configured with 2+
CORS origins had CORS silently broken for all of them.

These tests build an AWSOpenAPISpecEditor directly from a plain dict (no
AWS/network access needed) and inspect the generated OPTIONS integration.
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


def _allow_origin_value(editor, path="/hello"):
    options = editor.openapi_spec["paths"][path]["options"]
    integration = options["x-amazon-apigateway-integration"]
    return integration["responses"]["default"]["responseParameters"][
        "method.response.header.Access-Control-Allow-Origin"
    ]


@pytest.mark.unit
def test_single_origin_uses_static_value():
    editor = AWSOpenAPISpecEditor(_simple_spec())
    editor.cors_origins(["https://example.com"])

    assert _allow_origin_value(editor) == "'https://example.com'"


@pytest.mark.unit
def test_multiple_origins_produce_single_valid_value():
    editor = AWSOpenAPISpecEditor(_simple_spec())
    editor.cors_origins(["https://example.com", "https://other.example.com"])

    value = _allow_origin_value(editor)

    # Must not be a comma-joined list of origins - that's an invalid
    # Access-Control-Allow-Origin value browsers reject outright. Instead,
    # the requesting browser's own Origin header is reflected back.
    assert "," not in value
    assert value == "method.request.header.origin"
