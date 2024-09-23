"""An AWS Python Pulumi program"""

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
