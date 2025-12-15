# WebSocket API Technical Reference

This document provides technical details about the WebSocket API components in the cloud_foundry framework.

## Components

### WebSocketAPI

Pulumi component resource for AWS API Gateway V2 WebSocket APIs.

**Module**: `cloud_foundry.pulumi.websocket_api`

**Class**: `WebSocketAPI(pulumi.ComponentResource)`

#### Constructor Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| name | str | Yes | - | Name of the WebSocket API |
| routes | list[dict] | Yes | - | Route configurations (see Routes section) |
| authorizer | dict | No | None | Authorizer configuration (see Authorizers section) |
| hosted_zone_id | str | No | None | Route 53 hosted zone ID for custom domain |
| subdomain | str | No | None | Subdomain for custom domain |
| enable_logging | bool | No | False | Enable CloudWatch access logging |
| connection_table_arn | str\|Output | No | None | DynamoDB connection table ARN |
| export_api | str | No | None | Name to export API details |
| opts | ResourceOptions | No | None | Pulumi resource options |

#### Outputs

| Output | Type | Description |
|--------|------|-------------|
| api_id | Output[str] | API Gateway V2 API ID |
| stage_name | Output[str] | Stage name (defaults to Pulumi stack name) |
| domain | Output[str] | API endpoint URL |

#### Routes

Each route in the `routes` list must contain:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| route_key | str | Yes | Route identifier ($connect, $disconnect, $default, or custom) |
| function | Lambda.Function\|str | Yes | Lambda function or function name |
| require_auth | bool | No | Whether this route requires authorization |

**Required Routes**: While not enforced, it's strongly recommended to implement:
- `$connect` - Handles new connections
- `$disconnect` - Handles disconnections
- `$default` - Handles unmatched routes

**Custom Routes**: Any route key not starting with `$` is a custom route and must be specified in the client's message action field.

#### Authorizers

The `authorizer` parameter supports Lambda authorizers:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | str | Yes | Must be "lambda" |
| function | Lambda.Function\|str | Yes | Authorizer Lambda function |
| identity_source | str | No | Token location (default: "route.request.header.Authorization") |

Example identity sources:
- `route.request.header.Authorization` - Auth header
- `route.request.querystring.token` - Query parameter
- `route.request.header.X-API-Key` - Custom header

### WebSocketFunction

Specialized Lambda function for WebSocket route handlers.

**Module**: `cloud_foundry.pulumi.websocket_function`

**Class**: `WebSocketFunction(Function)`

Extends the base `Function` class with WebSocket-specific configuration.

#### Constructor Parameters

Inherits all parameters from `Function`, plus:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| connection_table_arn | str\|Output | No | None | DynamoDB connection table ARN |
| connection_table_name | str\|Output | No | None | Connection table name |
| api_endpoint | str\|Output | No | None | WebSocket API endpoint |

#### Automatic Configuration

When `connection_table_arn` is provided:
- Adds DynamoDB permissions (PutItem, GetItem, UpdateItem, DeleteItem, Query, Scan)
- Adds permissions for GSI queries
- Sets `CONNECTION_TABLE_NAME` environment variable

When `api_endpoint` is provided:
- Adds API Gateway Management API permissions (ManageConnections, Invoke)
- Sets `WEBSOCKET_API_ENDPOINT` environment variable

### ConnectionStore

DynamoDB table optimized for WebSocket connection management.

**Module**: `cloud_foundry.pulumi.connection_store`

**Class**: `ConnectionStore(pulumi.ComponentResource)`

#### Constructor Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| name | str | Yes | - | Connection store name |
| ttl_attribute | str | No | "ttl" | TTL attribute name |
| ttl_enabled | bool | No | True | Enable TTL for automatic cleanup |
| read_capacity | int | No | 5 | Read capacity (PROVISIONED mode) |
| write_capacity | int | No | 5 | Write capacity (PROVISIONED mode) |
| billing_mode | str | No | "PAY_PER_REQUEST" | Billing mode |
| global_secondary_indexes | list[dict] | No | [] | GSI configurations |
| opts | ResourceOptions | No | None | Pulumi resource options |

#### Schema

**Primary Key**:
- `connectionId` (String) - WebSocket connection ID

**Standard Attributes**:
- `userId` (String, optional) - User identifier
- `connectedAt` (String) - ISO timestamp of connection
- `ttl` (Number) - Unix timestamp for TTL
- `metadata` (Map, optional) - Additional connection data

#### Global Secondary Indexes

Each GSI configuration must include:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | str | Yes | Index name |
| hash_key | str | Yes | Partition key attribute |
| hash_key_type | str | No | Attribute type (default: "S") |
| range_key | str | No | Sort key attribute |
| range_key_type | str | No | Attribute type (default: "S") |
| projection_type | str | No | "ALL", "KEYS_ONLY", or "INCLUDE" |
| non_key_attributes | list[str] | No | Attributes for INCLUDE projection |
| read_capacity | int | No | Read capacity (PROVISIONED mode) |
| write_capacity | int | No | Write capacity (PROVISIONED mode) |

#### Outputs

| Output | Type | Description |
|--------|------|-------------|
| table_name | Output[str] | DynamoDB table name |
| table_arn | Output[str] | DynamoDB table ARN |

## Utility Functions

### websocket_utils Module

**Module**: `cloud_foundry.utils.websocket_utils`

This module provides helper functions for WebSocket Lambda handlers.

#### Connection Management

##### `store_connection(connection_id, user_id=None, metadata=None, ttl_hours=24)`

Store a WebSocket connection in DynamoDB.

**Parameters**:
- `connection_id` (str): WebSocket connection ID
- `user_id` (str, optional): User identifier
- `metadata` (dict, optional): Additional metadata
- `ttl_hours` (int): TTL in hours (default: 24)

**Returns**: dict - The stored connection item

**Raises**: ClientError if operation fails

##### `get_connection(connection_id)`

Retrieve a connection from DynamoDB.

**Parameters**:
- `connection_id` (str): WebSocket connection ID

**Returns**: dict or None - Connection item if found

##### `delete_connection(connection_id)`

Delete a connection from DynamoDB.

**Parameters**:
- `connection_id` (str): WebSocket connection ID

**Returns**: bool - True if successful

##### `update_connection(connection_id, updates)`

Update connection attributes.

**Parameters**:
- `connection_id` (str): WebSocket connection ID
- `updates` (dict): Attributes to update

**Returns**: dict or None - Updated connection item

#### Messaging

##### `send_message(connection_id, data)`

Send a message to a specific connection.

**Parameters**:
- `connection_id` (str): WebSocket connection ID
- `data` (Any): Message data (JSON-serializable)

**Returns**: bool - True if successful

**Notes**:
- Automatically handles GoneException (removes stale connections)
- Auto-encodes data to JSON if not already string/bytes

##### `broadcast_message(data, filter_fn=None)`

Broadcast a message to all (or filtered) connections.

**Parameters**:
- `data` (Any): Message data
- `filter_fn` (callable, optional): Filter function (conn) -> bool

**Returns**: dict - Statistics
- `sent` (int): Successful sends
- `failed` (int): Failed sends
- `filtered` (int): Filtered out connections

**Notes**:
- Handles DynamoDB pagination automatically
- Cleans up stale connections (GoneException)

##### `get_connections_by_user(user_id)`

Get all connections for a user.

**Parameters**:
- `user_id` (str): User identifier

**Returns**: list[dict] - Connection items

**Requires**: GSI named "userId-index" on userId attribute

##### `send_to_user(user_id, data)`

Send a message to all connections of a user.

**Parameters**:
- `user_id` (str): User identifier
- `data` (Any): Message data

**Returns**: dict - Statistics (sent, failed)

#### Response Helpers

##### `create_response(status_code, body=None)`

Create a standard Lambda response for WebSocket.

**Parameters**:
- `status_code` (int): HTTP status code
- `body` (Any, optional): Response body

**Returns**: dict - Lambda response object

## Event Structure

### WebSocket Events

#### $connect Event

```json
{
  "requestContext": {
    "routeKey": "$connect",
    "eventType": "CONNECT",
    "connectionId": "abc123",
    "requestId": "xyz789",
    "apiId": "api-id",
    "stage": "dev",
    "connectedAt": 1234567890
  },
  "queryStringParameters": {
    "userId": "user123",
    "token": "auth-token"
  },
  "headers": {
    "Host": "api-id.execute-api.region.amazonaws.com",
    "User-Agent": "..."
  }
}
```

#### $disconnect Event

```json
{
  "requestContext": {
    "routeKey": "$disconnect",
    "eventType": "DISCONNECT",
    "connectionId": "abc123",
    "requestId": "xyz789",
    "apiId": "api-id",
    "stage": "dev",
    "disconnectStatusCode": 1000,
    "disconnectReason": "Client-side close"
  }
}
```

#### Custom Route Event

```json
{
  "requestContext": {
    "routeKey": "sendMessage",
    "eventType": "MESSAGE",
    "connectionId": "abc123",
    "requestId": "xyz789",
    "apiId": "api-id",
    "stage": "dev"
  },
  "body": "{\"action\":\"sendMessage\",\"message\":\"Hello!\"}"
}
```

## IAM Permissions

### Required Lambda Permissions

For connection management:
```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem",
    "dynamodb:GetItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan"
  ],
  "Resource": "arn:aws:dynamodb:region:account:table/table-name"
}
```

For GSI queries:
```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:Query"],
  "Resource": "arn:aws:dynamodb:region:account:table/table-name/index/*"
}
```

For posting to connections:
```json
{
  "Effect": "Allow",
  "Action": [
    "execute-api:ManageConnections",
    "execute-api:Invoke"
  ],
  "Resource": "*"
}
```

### API Gateway Permissions

To invoke Lambda functions:
```json
{
  "Effect": "Allow",
  "Principal": {
    "Service": "apigateway.amazonaws.com"
  },
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:region:account:function:function-name",
  "Condition": {
    "ArnLike": {
      "AWS:SourceArn": "arn:aws:execute-api:region:account:api-id/*"
    }
  }
}
```

## Limits and Quotas

### API Gateway WebSocket API

- **Connection duration**: 2 hours (configurable)
- **Message size**: 128 KB
- **Connection requests**: 500 per second (soft limit)
- **Messages**: 10,000 per second per connection (soft limit)
- **Frame size**: 32 KB

### DynamoDB

- **Item size**: 400 KB
- **RCU (PAY_PER_REQUEST)**: Up to 40,000 per second
- **WCU (PAY_PER_REQUEST)**: Up to 40,000 per second
- **GSI per table**: 20

### Lambda

- **Concurrent executions**: 1,000 (soft limit)
- **Function timeout**: 15 minutes (900 seconds)
- **Environment variables**: 4 KB total

## Best Practices

### Connection Management

1. Always implement $connect and $disconnect handlers
2. Use TTL for automatic cleanup
3. Store minimal data in connection records
4. Use GSIs only for required queries

### Message Handling

1. Validate all input data
2. Handle GoneException gracefully
3. Implement retry logic for failed sends
4. Limit broadcast recipients with filters

### Security

1. Always use authorizers for production
2. Validate tokens on every message
3. Sanitize user input
4. Implement rate limiting
5. Use IAM policies with least privilege

### Performance

1. Use PAY_PER_REQUEST unless traffic is predictable
2. Batch DynamoDB operations when possible
3. Use connection pooling for boto3 clients
4. Cache connection lookups when appropriate
5. Implement pagination for large broadcasts

### Cost Optimization

1. Set appropriate TTL values
2. Use filters to reduce unnecessary sends
3. Monitor and adjust capacity settings
4. Clean up disconnected connections promptly
5. Use CloudWatch Insights to analyze usage

## Troubleshooting

### Common Issues

**Connection stores but doesn't receive messages**:
- Verify `WEBSOCKET_API_ENDPOINT` environment variable
- Check Lambda has `execute-api:ManageConnections` permission
- Ensure endpoint URL format is correct (https://, not wss://)

**GoneException when sending messages**:
- Normal for disconnected clients
- Implement cleanup in exception handler
- Consider implementing heartbeat/ping

**Authorizer denies all connections**:
- Check CloudWatch logs for authorizer errors
- Verify policy document format
- Ensure `principalId` is set in policy

**TTL not deleting items**:
- TTL takes up to 48 hours to delete items
- Verify TTL is enabled on table
- Check TTL attribute is a number (Unix timestamp)

## See Also

- [WebSocket API User Guide](websocket_user_guide.md)
- [Example: WebSocket Chat](../examples/websocket_chat/README.md)
- [AWS API Gateway WebSocket APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api.html)
- [DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
