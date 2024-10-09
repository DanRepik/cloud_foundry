# __main__.py

import cloud_foundry

API_SPEC = """
openapi: 3.0.3
info:
  description: A simple API that returns a greeting message.
  title: Greeting API
  version: 1.0.0
security:
  - oauth: []
paths:
  /greet:
    get:
      summary: Returns a greeting message.
      description: 'This endpoint returns a greeting message. It accepts an optional
        query parameter `name`. If `name` is not provided, it defaults to "World".'
      parameters:
        - description: The name of the person to greet.
          example: John
          in: query
          name: name
          required: false
          schema:
            type: string
      security:
        -  oauth: []
      responses:
        200:
          content:
            application/json:
              schema:
                properties:
                    message:
                      description: The greeting message.
                      example: Hello, John!
                      type: string
                type: object
          description: A greeting message.
        400:
          content:
            application/json:
              schema:
                properties:
                  error:
                    description: A description of the error.
                    example: Invalid query parameter
                    type: string
                type: object
          description: Bad Request - Invalid query parameter
"""

FUNCTION_CODE = """
import json

def handler(event, context):
    print(f"event: {event}")
    name = (event.get("queryStringParameters", None) or {}).get("name", "World")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"Hello, {name}!"
        }),
        "headers": {
            "Content-Type": "application/json"
        }
    }
"""

print(f"is_localstack: {cloud_foundry.is_localstack_deployment()}")

test_function = cloud_foundry.python_function(
    "test-function",
    handler="app.handler",
    memory_size=256,
    timeout=3,
    sources={"app.py": FUNCTION_CODE},
    requirements=[
        "requests==2.27.1",
    ],
)

rest_api = cloud_foundry.rest_api(
    "test-api",
    body=API_SPEC,
    integrations=[{"path": "/greet", "method": "get", "function": test_function}],
    authorizers=[
        {
            "type": "token",
            "name": "oauth",
            "function": cloud_foundry.import_function(
                ( "simple-oauth-server-local-validator" if cloud_foundry.is_localstack_deployment() else "simple-oauth-server-dev-validator")
            ),
        }
    ],
)
