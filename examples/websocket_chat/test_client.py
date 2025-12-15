#!/usr/bin/env python3
"""
Simple WebSocket test client for cloud_foundry WebSocket APIs.

Usage:
    python test_client.py wss://your-api.execute-api.region.amazonaws.com/stage

Optional parameters:
    --user-id USER_ID       User identifier
    --username USERNAME     Display name
    --message MESSAGE       Send a message after connecting
"""

import asyncio
import json
import sys
from datetime import datetime


try:
    import websockets
except ImportError:
    print("Error: websockets package not installed")
    print("Install it with: pip install websockets")
    sys.exit(1)


async def test_websocket(uri, user_id=None, username=None, message=None):
    """
    Connect to WebSocket API and test basic functionality.

    Args:
        uri: WebSocket URI
        user_id: Optional user ID
        username: Optional username
        message: Optional message to send
    """
    # Add query parameters if provided
    if user_id or username:
        params = []
        if user_id:
            params.append(f"userId={user_id}")
        if username:
            params.append(f"username={username}")
        uri = f"{uri}?{'&'.join(params)}"

    print(f"\n[{_timestamp()}] Connecting to {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            print(f"[{_timestamp()}] Connected! Connection ID available")

            # Send a test message if provided
            if message:
                await _send_message(websocket, message)

            # Start receiving messages
            print(f"[{_timestamp()}] Listening for messages...")
            print("Type messages to send (or 'quit' to exit):\n")

            # Create tasks for sending and receiving
            receive_task = asyncio.create_task(_receive_messages(websocket))
            send_task = asyncio.create_task(_send_from_stdin(websocket))

            # Wait for either task to complete
            done, pending = await asyncio.wait(
                [receive_task, send_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()

    except websockets.exceptions.WebSocketException as e:
        print(f"[{_timestamp()}] WebSocket error: {e}")
    except Exception as e:
        print(f"[{_timestamp()}] Error: {e}")
    finally:
        print(f"\n[{_timestamp()}] Disconnected")


async def _receive_messages(websocket):
    """Receive and print messages from the WebSocket."""
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                formatted = json.dumps(data, indent=2)
                print(f"\n[{_timestamp()}] Received: {formatted}")
            except json.JSONDecodeError:
                print(f"\n[{_timestamp()}] Received (raw): {message}")
            print("> ", end="", flush=True)
    except websockets.exceptions.ConnectionClosed:
        print(f"\n[{_timestamp()}] Connection closed by server")


async def _send_from_stdin(websocket):
    """Read messages from stdin and send them."""
    loop = asyncio.get_event_loop()
    while True:
        try:
            # Read from stdin asynchronously
            line = await loop.run_in_executor(None, sys.stdin.readline)
            line = line.strip()

            if not line:
                continue

            if line.lower() == "quit":
                print(f"[{_timestamp()}] Closing connection...")
                await websocket.close()
                break

            # Parse as JSON if it looks like JSON
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    await websocket.send(json.dumps(data))
                    print(f"[{_timestamp()}] Sent JSON: {line}")
                except json.JSONDecodeError:
                    print(f"[{_timestamp()}] Invalid JSON, sending as text")
                    await _send_message(websocket, line)
            else:
                await _send_message(websocket, line)

            print("> ", end="", flush=True)

        except Exception as e:
            print(f"\n[{_timestamp()}] Error sending: {e}")
            break


async def _send_message(websocket, text):
    """Send a text message as a broadcast."""
    message = {
        "action": "sendMessage",
        "type": "broadcast",
        "message": text,
    }
    await websocket.send(json.dumps(message))
    print(f"[{_timestamp()}] Sent: {text}")


def _timestamp():
    """Get current timestamp."""
    return datetime.now().strftime("%H:%M:%S")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="WebSocket test client for cloud_foundry APIs"
    )
    parser.add_argument("uri", help="WebSocket URI (wss://...)")
    parser.add_argument("--user-id", help="User ID")
    parser.add_argument("--username", help="Username")
    parser.add_argument("--message", help="Send a message after connecting")

    args = parser.parse_args()

    # Validate URI
    if not args.uri.startswith(("ws://", "wss://")):
        print("Error: URI must start with ws:// or wss://")
        sys.exit(1)

    print("=" * 60)
    print("WebSocket Test Client")
    print("=" * 60)
    print("\nCommands:")
    print("  <text>                 - Send broadcast message")
    print("  {\"json\": \"data\"}       - Send raw JSON")
    print("  quit                   - Disconnect and exit")
    print("=" * 60)

    try:
        asyncio.run(
            test_websocket(
                args.uri,
                user_id=args.user_id,
                username=args.username,
                message=args.message,
            )
        )
    except KeyboardInterrupt:
        print(f"\n[{_timestamp()}] Interrupted by user")
    except Exception as e:
        print(f"[{_timestamp()}] Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
