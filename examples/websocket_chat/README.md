# WebSocket Chat Example

This example demonstrates how to build a real-time chat application using WebSocket APIs with the cloud_foundry framework.

## Features

- **Connection Management**: Automatic tracking of WebSocket connections in DynamoDB
- **Message Broadcasting**: Send messages to all connected users
- **Direct Messaging**: Send messages to specific users
- **User Identification**: Support for user IDs and usernames
- **Automatic Cleanup**: TTL-based cleanup of stale connections
- **Logging**: CloudWatch logs for all WebSocket events

## Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ WebSocket
       ▼
┌─────────────────────────┐
│  API Gateway WebSocket  │
│  API (V2)              │
└────┬────────────────┬───┘
     │                │
     │ Routes:        │
     │ - $connect     │
     │ - $disconnect  │
     │ - sendMessage  │
     │ - $default     │
     │                │
     ▼                ▼
┌─────────────┐  ┌──────────────┐
│   Lambda    │  │   Lambda     │
│  Functions  │  │  Functions   │
└─────┬───────┘  └──────┬───────┘
      │                 │
      ▼                 ▼
┌───────────────────────────┐
│  DynamoDB Table           │
│  (Connection Store)       │
│  - connectionId (PK)      │
│  - userId (GSI)           │
│  - metadata               │
│  - ttl                    │
└───────────────────────────┘
```

## Deployment

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Deploy the stack:
```bash
pulumi up
```

3. Note the WebSocket URL from the outputs:
```bash
pulumi stack output websocket_url
```

## Usage

### Connecting to the WebSocket API

Connect to the WebSocket API with optional user information:

```javascript
// Basic connection
const ws = new WebSocket('wss://your-api-id.execute-api.region.amazonaws.com/stage');

// Connection with user info
const ws = new WebSocket(
  'wss://your-api-id.execute-api.region.amazonaws.com/stage' +
  '?userId=user123&username=JohnDoe'
);
```

### Sending Messages

#### Broadcast to All Users

```javascript
ws.send(JSON.stringify({
  type: 'broadcast',
  message: 'Hello everyone!'
}));
```

#### Direct Message to a User

```javascript
ws.send(JSON.stringify({
  type: 'direct',
  targetUser: 'user456',
  message: 'Hi there!'
}));
```

### Receiving Messages

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`${data.sender}: ${data.content}`);
};
```

## Routes

### $connect
- **Trigger**: New WebSocket connection
- **Function**: `handlers/connect.py`
- **Action**: 
  - Store connection in DynamoDB
  - Extract user info from query params
  - Set TTL for automatic cleanup

### $disconnect
- **Trigger**: WebSocket disconnection
- **Function**: `handlers/disconnect.py`
- **Action**: Remove connection from DynamoDB

### sendMessage
- **Trigger**: Custom route for sending messages
- **Function**: `handlers/send_message.py`
- **Payload**:
  ```json
  {
    "type": "broadcast|direct",
    "message": "Your message",
    "targetUser": "userId" // for direct messages
  }
  ```

### $default
- **Trigger**: Any unmatched route
- **Function**: `handlers/default.py`
- **Action**: Return error for unknown routes

## Connection Store Schema

The DynamoDB table stores connections with the following attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| connectionId | String (PK) | WebSocket connection ID |
| userId | String | User identifier (GSI) |
| connectedAt | String | ISO timestamp of connection |
| ttl | Number | Unix timestamp for TTL cleanup |
| metadata | Map | Additional user information (username, etc.) |

## Environment Variables

The Lambda functions automatically receive:

- `CONNECTION_TABLE_NAME`: Name of the DynamoDB connection table
- `WEBSOCKET_API_ENDPOINT`: WebSocket API endpoint for posting messages

## Testing Locally

Use `wscat` to test the WebSocket API:

```bash
# Install wscat
npm install -g wscat

# Connect to the API
wscat -c "wss://your-api-id.execute-api.region.amazonaws.com/stage?userId=test123&username=TestUser"

# Send a broadcast message
> {"type":"broadcast","message":"Hello from wscat!"}

# Send a direct message
> {"type":"direct","targetUser":"user456","message":"Private message"}
```

## Cleanup

Remove all resources:

```bash
pulumi destroy
```

## Extending the Example

### Add Authentication

Add a Lambda authorizer to validate tokens:

```python
websocket_api = WebSocketAPI(
    "chat-api",
    routes=[...],
    authorizer={
        "type": "lambda",
        "function": authorizer_function.lambda_,
        "identity_source": "route.request.querystring.token",
    },
)
```

### Add Custom Routes

Add more routes for additional features:

```python
routes = [
    # ... existing routes ...
    {
        "route_key": "typing",
        "function": typing_indicator_function.lambda_,
    },
    {
        "route_key": "presence",
        "function": presence_function.lambda_,
    },
]
```

### Add Custom Domain

Configure a custom domain for the WebSocket API:

```python
websocket_api = WebSocketAPI(
    "chat-api",
    routes=[...],
    hosted_zone_id="Z1234567890ABC",
    subdomain="chat",
)
```

## Learn More

- [AWS API Gateway WebSocket APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api.html)
- [WebSocket Protocol](https://tools.ietf.org/html/rfc6455)
- [DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
