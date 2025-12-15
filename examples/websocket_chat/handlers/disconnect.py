"""
WebSocket Disconnect Handler

Handles WebSocket disconnections and removes connections from DynamoDB.
"""

import sys
import os

# Add parent directory to path to import websocket_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cloud_foundry.utils.websocket_utils import (  # noqa: E402
    delete_connection,
    create_response,
)


def handler(event, context):  # noqa: ARG001
    """
    Handle WebSocket $disconnect route.

    Removes the connection from DynamoDB.

    Args:
        event: API Gateway WebSocket event
        context: Lambda context

    Returns:
        dict: Response with status code
    """
    connection_id = event["requestContext"]["connectionId"]

    try:
        delete_connection(connection_id)
        print(f"Connection disconnected: {connection_id}")
        return create_response(200)

    except Exception as e:  # noqa: BLE001
        print(f"Error deleting connection: {str(e)}")
        # Return success anyway since the connection is gone
        return create_response(200)
