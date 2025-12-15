"""
WebSocket Send Message Handler

Handles message sending and broadcasting in the chat application.
"""

import json
import sys
import os

# Add parent directory to path to import websocket_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cloud_foundry.utils.websocket_utils import (  # noqa: E402
    broadcast_message,
    send_to_user,
    get_connection,
    create_response,
)


def handler(event, context):  # noqa: ARG001
    """
    Handle WebSocket sendMessage route.

    Supports two message types:
    - broadcast: Send to all connected users
    - direct: Send to a specific user

    Args:
        event: API Gateway WebSocket event
        context: Lambda context

    Returns:
        dict: Response with status code
    """
    connection_id = event["requestContext"]["connectionId"]

    try:
        # Parse the message body
        body = json.loads(event.get("body", "{}"))
        message_type = body.get("type", "broadcast")
        message_content = body.get("message", "")

        if not message_content:
            return create_response(400, {"error": "Message content required"})

        # Get sender information
        sender_conn = get_connection(connection_id)
        sender_name = "Anonymous"
        if sender_conn and sender_conn.get("metadata"):
            sender_name = sender_conn["metadata"].get("username", "Anonymous")

        # Prepare the message to send
        outgoing_message = {
            "type": "message",
            "sender": sender_name,
            "content": message_content,
        }

        # Handle different message types
        if message_type == "broadcast":
            # Broadcast to all connections
            stats = broadcast_message(outgoing_message)
            print(
                f"Broadcast message from {sender_name}: "
                f"sent={stats['sent']}, failed={stats['failed']}"
            )

        elif message_type == "direct":
            # Send to specific user
            target_user = body.get("targetUser")
            if not target_user:
                return create_response(
                    400, {"error": "targetUser required for direct messages"}
                )

            stats = send_to_user(target_user, outgoing_message)
            print(
                f"Direct message from {sender_name} to {target_user}: "
                f"sent={stats['sent']}, failed={stats['failed']}"
            )

        else:
            return create_response(
                400, {"error": f"Unknown message type: {message_type}"}
            )

        return create_response(200, {"status": "Message sent"})

    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON"})

    except Exception as e:  # noqa: BLE001
        print(f"Error sending message: {str(e)}")
        return create_response(500, {"error": "Failed to send message"})
