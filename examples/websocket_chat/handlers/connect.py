"""
WebSocket Connect Handler

Handles new WebSocket connections and stores them in DynamoDB.
"""

import sys
import os

# Add parent directory to path to import websocket_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cloud_foundry.utils.websocket_utils import (  # noqa: E402
    store_connection,
    create_response,
)


def handler(event, context):  # noqa: ARG001
    """
    Handle WebSocket $connect route.

    Stores the connection in DynamoDB with optional user information
    from query string parameters.

    Args:
        event: API Gateway WebSocket event
        context: Lambda context

    Returns:
        dict: Response with status code
    """
    connection_id = event["requestContext"]["connectionId"]

    # Extract user information from query parameters if available
    query_params = event.get("queryStringParameters") or {}
    user_id = query_params.get("userId")
    username = query_params.get("username")

    # Prepare metadata
    metadata = {}
    if username:
        metadata["username"] = username

    # Store the connection
    try:
        store_connection(
            connection_id=connection_id,
            user_id=user_id,
            metadata=metadata,
            ttl_hours=24,
        )

        print(f"Connection established: {connection_id}")
        if user_id:
            print(f"  User ID: {user_id}")
        if username:
            print(f"  Username: {username}")

        return create_response(200)

    except Exception as e:  # noqa: BLE001
        print(f"Error storing connection: {str(e)}")
        return create_response(
            500, {"error": "Failed to establish connection"}
        )
