"""
WebSocket Default Handler

Handles unmatched WebSocket routes.
"""

import sys
import os

# Add parent directory to path to import websocket_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cloud_foundry.utils.websocket_utils import create_response  # noqa: E402


def handler(event, context):  # noqa: ARG001
    """
    Handle WebSocket $default route.

    This is called for any route that doesn't match a defined route.

    Args:
        event: API Gateway WebSocket event
        context: Lambda context

    Returns:
        dict: Response with status code
    """
    route_key = event["requestContext"].get("routeKey", "unknown")
    print(f"Unmatched route: {route_key}")

    return create_response(
        400,
        {
            "error": f"Unknown route: {route_key}",
            "message": "Supported routes: sendMessage",
        },
    )
