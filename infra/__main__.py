# __main__.py

import cloud_foundry

cloud_foundry.python_function(
  "test-function",
  handler="app.lambda_handler",
  memory_size=256,
  timeout=3,
  sources={
    "app.py": """
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
  }
)

rest_api = cloud_foundry.rest_api(
  "rest-api",
  body="""
openapi: 3.0.3
info:
  title: Auth0 Mock Token Service
  description: A mock service for generating and validating Auth0 tokens.
  version: 1.0.0
paths:
  /token:
    post:
      summary: Generate a mock Auth0 JWT token
      description: This endpoint generates a mock JWT token using the provided client credentials.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                client_id:
                  type: string
                  description: The client ID associated with the application.
                  example: client_1
                client_secret:
                  type: string
                  description: The client secret associated with the application.
                  example: your-client-secret
                audience:
                  type: string
                  description: The API audience.
                  example: https://api.example.com/
                grant_type:
                  type: string
                  description: The OAuth grant type (must be 'client_credentials').
                  example: client_credentials
              required:
                - client_id
                - client_secret
                - audience
                - grant_type
      responses:
        '200':
          description: Successfully generated JWT token
          content:
            application/json:
              schema:
                type: object
                properties:
                  access_token:
                    type: string
                    description: The generated JWT access token.
                    example: eyJhbGciOiJ...abc123
                  token_type:
                    type: string
                    description: The type of token (usually Bearer).
                    example: Bearer
                  expires_in:
                    type: integer
                    description: Expiration time of the token in seconds.
                    example: 86400
...
"""
)

