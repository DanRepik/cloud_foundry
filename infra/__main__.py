# __main__.py

import cloud_foundry

API_SPEC = """
openapi: 3.0.3
info:
  title: Greeting API
  description: A simple API that returns a greeting message.
  version: 1.0.0
paths:
  /greet:
    get:
      summary: Returns a greeting message.
      description: This endpoint returns a greeting message. It accepts an optional query parameter `name`. If `name` is not provided, it defaults to "World".
      parameters:
        - in: query
          name: name
          schema:
            type: string
          required: false
          description: The name of the person to greet.
          example: John
      responses:
        '200':
          description: A greeting message.
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                    description: The greeting message.
                    example: Hello, John!
        '400':
          description: Bad Request - Invalid query parameter
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    description: A description of the error.
                    example: Invalid query parameter
"""

FUNCTION_CODE = """
import json

def lambda_handler(event, context):
    name = event.get("queryStringParameters", {}).get("name", "World")
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


test_function = cloud_foundry.python_function(
    "test-function",
    handler="app.lambda_handler",
    memory_size=256,
    timeout=3,
    sources={"app.py": FUNCTION_CODE},
)

rest_api = cloud_foundry.rest_api(
    "test-api",
    body=API_SPEC,
    integrations=[
        { "path":"/greet", "method":"get", "function":test_function}
    ],
)
