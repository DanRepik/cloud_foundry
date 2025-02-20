import json
from typing import Optional

from cloud_foundry.utils.logger import logger

log = logger(__name__)


class OpenAPIGenerator:
    def __init__(
        self,
        title="API",
        version="1.0.0",
        description="Generated OpenAPI Spec",
        existing_spec=None,
    ):
        self.openapi = (
            existing_spec
            if existing_spec
            else {
                "openapi": "3.0.3",
                "info": {
                    "title": title,
                    "version": version,
                    "description": description,
                },
                "paths": {},
                "components": {"schemas": {}, "securitySchemes": {}},
            }
        )

    def add_path(
        self,
        path,
        method,
        summary=None,
        description=None,
        parameters=None,
        request_body=None,
        responses=None,
    ):
        if path not in self.openapi["paths"]:
            self.openapi["paths"][path] = {}
        operation = {}
        if summary:
            operation["summary"] = summary
        if description:
            operation["description"] = description
        if responses:
            operation["responses"] = responses
        if parameters:
            operation["parameters"] = parameters
        if request_body:
            operation["requestBody"] = {
                "content": {"application/json": {"schema": request_body}}
            }
        self.openapi["paths"][path][method.lower()] = operation

    def add_schema(self, name, schema):
        self.openapi["components"]["schemas"][name] = schema

    def add_s3_integration(
        self,
        path,
        bucket_name,
        object_key,
        summary: Optional[str] = None,
        description: Optional[str] = None,
    ):
        log.info(f"path: {path}")
        if path not in self.openapi["paths"]:
            self.openapi["paths"][path] = {}
        self.openapi["paths"][path]["get"] = {
            "summary": summary,
            "description": description,
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {"application/octet-stream": {}},
                }
            },
            "x-amazon-apigateway-integration": {
                "type": "aws",
                "uri": f"arn:aws:apigateway:region:s3:path/{bucket_name}/{object_key}",
                "httpMethod": "GET",
                "passthroughBehavior": "when_no_match",
                "responses": {"default": {"statusCode": "200"}},
            },
        }

    def generate_spec(self, file_path=None):
        spec = json.dumps(self.openapi, indent=2)
        if file_path:
            with open(file_path, "w") as file:
                file.write(spec)
        return spec


class AWSOpenAPIGenerator(OpenAPIGenerator):
    def __init__(
        self,
        title="AWS API",
        version="1.0.0",
        description="AWS OpenAPI Spec",
        existing_spec=None,
    ):
        super().__init__(title, version, description, existing_spec)
        self.openapi["components"].setdefault("securitySchemes", {})
        self.openapi["components"]["securitySchemes"]["apiKeyAuth"] = {
            "type": "apiKey",
            "name": "x-api-key",
            "in": "header",
        }

    def add_lambda_function(
        self,
        path,
        method,
        function_arn,
        region,
        summary=None,
        description=None,
        parameters=None,
        request_body=None,
        responses=None,
    ):
        if path not in self.openapi["paths"]:
            self.openapi["paths"][path] = {}
        operation = {
            "security": [{"apiKeyAuth": []}],
            "x-amazon-apigateway-integration": {
                "uri": f"arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{function_arn}/invocations",
                "httpMethod": "POST",
                "type": "aws_proxy",
            },
        }
        if summary:
            operation["summary"] = summary
        if description:
            operation["description"] = description
        if responses:
            operation["responses"] = responses
        if parameters:
            operation["parameters"] = parameters
        if request_body:
            operation["requestBody"] = {
                "content": {"application/json": {"schema": request_body}}
            }
        self.openapi["paths"][path][method.lower()] = operation


# Example usage:
existing_spec = {
    "openapi": "3.0.3",
    "info": {
        "title": "Pre-existing API",
        "version": "1.0",
        "description": "API with existing specification",
    },
    "paths": {},
    "components": {"schemas": {}, "securitySchemes": {}},
}

aws_api = AWSOpenAPIGenerator(existing_spec=existing_spec)

# Add a schema
aws_api.add_schema(
    "User",
    {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},
        },
        "required": ["id", "name"],
    },
)

# Add a Lambda function as an API Gateway integration
aws_api.add_lambda_function(
    path="/users",
    method="get",
    function_arn="arn:aws:lambda:us-east-1:123456789012:function:getUsers",
    region="us-east-1",
    summary="Get all users",
    description="Returns a list of users from AWS Lambda",
    responses={
        "200": {
            "description": "A list of users",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/User"},
                    }
                }
            },
        }
    },
)
