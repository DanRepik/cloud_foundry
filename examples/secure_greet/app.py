# app.py
import json


def handler(event, _):
    print(event)
    print(f"username: {event.get('requestContext', {})}")
    name = (event.get("queryStringParameters") or {}).get("name", "World")

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Hello, {name}!"}),
        "headers": {"Content-Type": "application/json"},
    }
