# WebSocket API User Guide

This guide explains how to use the cloud_foundry WebSocket components to build real-time, bidirectional communication applications.

## Overview

The cloud_foundry WebSocket support includes:

- **WebSocketAPI**: Pulumi component for creating API Gateway V2 WebSocket APIs
- **WebSocketFunction**: Specialized Lambda function with WebSocket utilities
- **ConnectionStore**: DynamoDB table for managing active connections
- **websocket_utils**: Python utilities for connection and message management

## Quick Start

### 1. Create a Connection Store

The connection store maintains active WebSocket connections:

```python
from cloud_foundry.pulumi.connection_store import ConnectionStore

connection_store = ConnectionStore(
    "my-connections",
    global_secondary_indexes=[
        {
            "name": "userId-index",
            "hash_key": "userId",
            "projection_type": "ALL",
        }
    ],
)
```

### 2. Create Lambda Functions

Create handlers for WebSocket routes:

```python
from cloud_foundry.pulumi.websocket_function import WebSocketFunction
from cloud_foundry.python_archive_builder import PythonArchiveBuilder

# Build the deployment package
connect_archive = PythonArchiveBuilder(
    "connect-handler",
    source_path="handlers/connect.py",
    requirements=["boto3"],
)

# Create the function
connect_function = WebSocketFunction(
    "connect-handler",
    archive_location=connect_archive.archive_path,
    hash=connect_archive.source_code_hash,
    runtime="python3.13",
    handler="connect.handler",
    connection_table_arn=connection_store.table_arn,
    connection_table_name=connection_store.table_name,
)
```

### 3. Create the WebSocket API

Wire everything together:

```python
from cloud_foundry.pulumi.websocket_api import WebSocketAPI

websocket_api = WebSocketAPI(
    "my-api",
    routes=[
        {
            "route_key": "$connect",
            "function": connect_function.lambda_,
        },
        {
            "route_key": "$disconnect",
            "function": disconnect_function.lambda_,
        },
        {
            "route_key": "sendMessage",
            "function": send_message_function.lambda_,
        },
        {
            "route_key": "$default",
            "function": default_function.lambda_,
        },
    ],
    enable_logging=True,
)
```

## Components Reference

### WebSocketAPI

Creates an API Gateway V2 WebSocket API with Lambda integrations.

#### Parameters

- `name` (str): API name
- `routes` (list[dict]): Route configurations
  - `route_key` (str): Route identifier ($connect, $disconnect, $default, or custom)
  - `function`: Lambda function for the route
  - `require_auth` (bool, optional): Require authorization for this route
- `authorizer` (dict, optional): Authorizer configuration
  - `type` (str): "lambda" or "cognito"
  - `function`: Lambda authorizer function
  - `identity_source` (str): Token location (e.g., "route.request.querystring.token")
- `hosted_zone_id` (str, optional): Route 53 hosted zone for custom domain
- `subdomain` (str, optional): Subdomain for custom domain
- `enable_logging` (bool): Enable CloudWatch logs
- `connection_table_arn` (str, optional): DynamoDB connection table ARN

#### Example with Authorization

```python
websocket_api = WebSocketAPI(
    "secure-api",
    routes=[...],
    authorizer={
        "type": "lambda",
        "function": auth_function.lambda_,
        "identity_source": "route.request.header.Authorization",
    },
)
```

#### Example with Custom Domain

```python
websocket_api = WebSocketAPI(
    "api",
    routes=[...],
    hosted_zone_id="Z1234567890ABC",
    subdomain="ws",
)
```

### WebSocketFunction

Extended Lambda function with WebSocket-specific features.

#### Parameters

Inherits all `Function` parameters, plus:

- `connection_table_arn` (str|Output, optional): Connection table ARN
- `connection_table_name` (str|Output, optional): Connection table name
- `api_endpoint` (str|Output, optional): WebSocket API endpoint

#### Automatic Features

- DynamoDB permissions for connection table
- API Gateway Management API permissions
- Environment variables for table name and API endpoint

### ConnectionStore

DynamoDB table optimized for WebSocket connections.

#### Parameters

- `name` (str): Table name
- `ttl_attribute` (str): TTL attribute name (default: "ttl")
- `ttl_enabled` (bool): Enable TTL cleanup (default: True)
- `billing_mode` (str): "PAY_PER_REQUEST" or "PROVISIONED"
- `read_capacity` (int): Read capacity units (PROVISIONED mode)
- `write_capacity` (int): Write capacity units (PROVISIONED mode)
- `global_secondary_indexes` (list[dict]): GSI configurations

#### Example with GSI

```python
connection_store = ConnectionStore(
    "connections",
    global_secondary_indexes=[
        {
            "name": "userId-index",
            "hash_key": "userId",
            "projection_type": "ALL",
        },
        {
            "name": "roomId-index",
            "hash_key": "roomId",
            "range_key": "connectedAt",
            "projection_type": "INCLUDE",
            "non_key_attributes": ["username"],
        },
    ],
)
```

## Handler Utilities

The `websocket_utils` module provides helper functions for Lambda handlers.

### Connection Management

```python
from cloud_foundry.utils.websocket_utils import (
    store_connection,
    get_connection,
    delete_connection,
    update_connection,
)

# Store a new connection
store_connection(
    connection_id="abc123",
    user_id="user456",
    metadata={"username": "john", "room": "general"},
    ttl_hours=24,
)

# Get connection info
conn = get_connection("abc123")

# Update connection
update_connection("abc123", {"room": "random"})

# Delete connection
delete_connection("abc123")
```

### Messaging

```python
from cloud_foundry.utils.websocket_utils import (
    send_message,
    broadcast_message,
    send_to_user,
)

# Send to one connection
send_message("abc123", {"type": "notification", "text": "Hello"})

# Broadcast to all
stats = broadcast_message({"type": "announcement", "text": "System update"})
print(f"Sent to {stats['sent']} connections")

# Broadcast with filter
stats = broadcast_message(
    {"type": "room_message", "text": "Hi room!"},
    filter_fn=lambda conn: conn.get("metadata", {}).get("room") == "general"
)

# Send to all connections of a user
stats = send_to_user("user456", {"type": "direct", "text": "Private message"})
```

### Response Helpers

```python
from cloud_foundry.utils.websocket_utils import create_response

# Success response
return create_response(200)

# Error response
return create_response(400, {"error": "Invalid message format"})
```

## Route Handlers

### $connect Handler

Called when a client connects. Store the connection and extract user info:

```python
def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    query_params = event.get("queryStringParameters") or {}

    store_connection(
        connection_id=connection_id,
        user_id=query_params.get("userId"),
        metadata={"username": query_params.get("username")},
    )

    return create_response(200)
```

### $disconnect Handler

Called when a client disconnects. Clean up the connection:

```python
def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    delete_connection(connection_id)
    return create_response(200)
```

### Custom Route Handlers

Handle custom routes for your application logic:

```python
def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body", "{}"))

    # Your business logic
    message = body.get("message")

    # Broadcast to others
    broadcast_message(
        {"sender": connection_id, "message": message},
        filter_fn=lambda c: c["connectionId"] != connection_id
    )

    return create_response(200)
```

### $default Handler

Catch-all for undefined routes:

```python
def handler(event, context):
    route_key = event["requestContext"].get("routeKey")
    return create_response(
        400,
        {"error": f"Unknown route: {route_key}"}
    )
```

## Client Usage

### JavaScript/Browser

```javascript
// Connect
const ws = new WebSocket(
  'wss://abc123.execute-api.us-east-1.amazonaws.com/dev' +
  '?userId=user123&username=John'
);

// Handle connection
ws.onopen = () => {
  console.log('Connected');

  // Send a message
  ws.send(JSON.stringify({
    action: 'sendMessage',  // Route key
    message: 'Hello!'
  }));
};

// Receive messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};

// Handle errors
ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

// Handle close
ws.onclose = () => {
  console.log('Disconnected');
};
```

### Python Client

```python
import asyncio
import websockets
import json

async def connect():
    uri = "wss://abc123.execute-api.us-east-1.amazonaws.com/dev"

    async with websockets.connect(uri) as websocket:
        # Send message
        await websocket.send(json.dumps({
            "action": "sendMessage",
            "message": "Hello from Python!"
        }))

        # Receive messages
        async for message in websocket:
            data = json.loads(message)
            print(f"Received: {data}")

asyncio.run(connect())
```

## Best Practices

### Connection Lifecycle

1. **Always implement $connect and $disconnect**: These are essential for proper connection management
2. **Use TTL for cleanup**: Set reasonable TTL values to automatically clean up stale connections
3. **Handle errors gracefully**: Connection failures should clean up resources

### Message Handling

1. **Validate input**: Always validate message payloads before processing
2. **Handle GoneException**: Remove connections that no longer exist
3. **Limit message size**: Consider implementing size limits for messages
4. **Use action/type field**: Include a field to route different message types

### Performance

1. **Use PAY_PER_REQUEST billing**: Unless you have consistent high traffic
2. **Implement pagination**: When broadcasting to many connections
3. **Use GSIs wisely**: Index only what you need to query
4. **Cache connection queries**: Reduce DynamoDB reads when possible

### Security

1. **Use authorizers**: Implement Lambda or Cognito authorizers
2. **Validate tokens**: Check authorization on each message
3. **Sanitize data**: Prevent injection attacks
4. **Rate limit**: Implement rate limiting for actions

## Advanced Patterns

### Room-based Chat

Store room information in connection metadata:

```python
# On connect
store_connection(
    connection_id=connection_id,
    user_id=user_id,
    metadata={"room": "general"}
)

# Broadcast to room
broadcast_message(
    message,
    filter_fn=lambda c: c.get("metadata", {}).get("room") == target_room
)
```

### Presence Tracking

Use GSI to query online users:

```python
# Add presence status
update_connection(connection_id, {"status": "online"})

# Query online users in room
# (Requires GSI on room + status)
```

### Message History

Store messages in a separate DynamoDB table for history:

```python
messages_table.put_item(Item={
    "messageId": str(uuid.uuid4()),
    "roomId": room_id,
    "timestamp": datetime.now().isoformat(),
    "sender": user_id,
    "content": message,
})
```

## Troubleshooting

### Connection not stored

- Check CloudWatch logs for the $connect handler
- Verify CONNECTION_TABLE_NAME environment variable
- Ensure Lambda has DynamoDB permissions

### Messages not received

- Verify WEBSOCKET_API_ENDPOINT is set correctly
- Check for GoneException in logs (stale connections)
- Ensure Lambda has execute-api:ManageConnections permission

### Authorizer failing

- Check CloudWatch logs for the authorizer function
- Verify identity_source matches token location
- Ensure authorizer returns proper policy document

### Custom domain not working

- Verify certificate is validated
- Check Route53 record creation
- Allow time for DNS propagation

## Examples

See `examples/websocket_chat/` for a complete chat application demonstrating:

- Connection management
- Broadcast messaging
- Direct messaging
- User presence
- Room support

## Next Steps

- Add authentication with Lambda authorizers
- Implement rate limiting
- Add message persistence
- Build a web client
- Add file/image sharing
- Implement typing indicators
