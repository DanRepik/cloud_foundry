from cloud_foundry import python_function

lambda_function = python_function(
    name="example-function",
    environment={
        "ENV": "production",
    },
    runtime="python3.11",
    sources={
        "app.py": """
import os
import json

def handler(event, context):
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f\"Hello from {os.environ.get('ENV', 'unknown')}!\"
        }),
        'headers': {
            'Content-Type': 'application/json'
        }
    }
""",
    },
)
