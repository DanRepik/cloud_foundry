# WebSocket Support Implementation Summary

## Overview

This implementation adds comprehensive WebSocket support to the cloud_foundry framework, enabling real-time bidirectional communication for cloud applications.

## Components Created

### 1. Core Infrastructure Components

#### `cloud_foundry/pulumi/websocket_api.py`
- **WebSocketAPI** component for AWS API Gateway V2 WebSocket APIs
- Supports multiple routes ($connect, $disconnect, $default, custom routes)
- Lambda authorizer integration
- Custom domain support
- CloudWatch logging
- Route-level authorization configuration

#### `cloud_foundry/pulumi/websocket_function.py`
- **WebSocketFunction** - Specialized Lambda function for WebSocket handlers
- Extends base Function class with WebSocket-specific features
- Auto-configures DynamoDB permissions for connection management
- Auto-configures API Gateway Management API permissions
- Environment variables for connection table and API endpoint

#### `cloud_foundry/pulumi/connection_store.py`
- **ConnectionStore** - DynamoDB table for managing WebSocket connections
- Primary key: connectionId
- Optional attributes: userId, metadata, connectedAt
- TTL support for automatic cleanup
- Global Secondary Index (GSI) support for custom queries
- Configurable billing mode (PAY_PER_REQUEST or PROVISIONED)

### 2. Utility Functions

#### `cloud_foundry/utils/websocket_utils.py`
Helper functions for Lambda handlers:

**Connection Management:**
- `store_connection()` - Save connection to DynamoDB
- `get_connection()` - Retrieve connection details
- `delete_connection()` - Remove connection
- `update_connection()` - Update connection attributes

**Messaging:**
- `send_message()` - Send to specific connection
- `broadcast_message()` - Send to all/filtered connections
- `send_to_user()` - Send to all connections of a user
- `get_connections_by_user()` - Query connections by user

**Response Helpers:**
- `create_response()` - Create standard Lambda responses

### 3. Example Application

#### `examples/websocket_chat/`
Complete WebSocket chat application demonstrating:
- Connection lifecycle management
- Broadcast messaging
- Direct user-to-user messaging
- User identification and metadata
- Multiple Lambda handlers for different routes

**Files:**
- `__main__.py` - Pulumi infrastructure code
- `handlers/connect.py` - Connection handler
- `handlers/disconnect.py` - Disconnection handler
- `handlers/send_message.py` - Message routing handler
- `handlers/default.py` - Fallback handler
- `test_client.py` - Interactive test client
- `README.md` - Usage documentation
- `Pulumi.yaml` - Project configuration
- `requirements.txt` - Dependencies

### 4. Documentation

#### `docs/websocket_user_guide.md`
Comprehensive user guide covering:
- Quick start tutorial
- Component reference
- Handler utilities
- Client usage examples (JavaScript, Python)
- Best practices
- Advanced patterns (rooms, presence, message history)
- Troubleshooting

#### `docs/websocket_api.md`
Technical reference including:
- API specifications for all components
- Event structure details
- IAM permissions
- AWS limits and quotas
- Common issues and solutions

#### Updated `examples/readme.md`
Added WebSocket chat example to the examples listing

## Features

### Configuration Options

**WebSocket API:**
- Multiple route support (system and custom)
- Lambda or Cognito authorization
- Custom domain with SSL
- Access logging to CloudWatch
- Stage configuration

**Connection Store:**
- Flexible schema with metadata support
- TTL-based cleanup
- GSI for custom queries
- Configurable billing mode
- Automatic capacity management

**Lambda Functions:**
- Pre-configured permissions
- Environment variable injection
- Standard Function features (VPC, timeout, memory, etc.)

### Route Types

1. **$connect** - New connection establishment
2. **$disconnect** - Connection termination
3. **$default** - Catch-all for unmatched routes
4. **Custom routes** - Application-specific message handling

### Security

- Lambda authorizer support
- Token validation from headers/query strings
- IAM-based permissions
- VPC support for Lambda functions

### Scalability

- Pay-per-request billing by default
- Automatic cleanup via TTL
- Efficient broadcasting with filters
- GSI-based user queries

## Integration Points

### With Existing Components

The WebSocket components integrate seamlessly with:
- **Function** - Base class extended by WebSocketFunction
- **CustomDomain** - Reused for WebSocket custom domains
- **LogGroup** - CloudWatch logging pattern
- **Python Archive Builder** - Lambda deployment packages

### AWS Services Used

- **API Gateway V2** - WebSocket API management
- **Lambda** - Route handlers and authorizers
- **DynamoDB** - Connection state storage
- **Route 53** - Custom domain DNS
- **ACM** - SSL certificates
- **CloudWatch** - Access and application logs
- **IAM** - Permissions and policies

## Usage Pattern

```python
# 1. Create connection store
connection_store = ConnectionStore("connections", ...)

# 2. Create Lambda functions
connect_fn = WebSocketFunction("connect", 
    connection_table_arn=connection_store.table_arn, ...)

# 3. Create WebSocket API
api = WebSocketAPI("api",
    routes=[
        {"route_key": "$connect", "function": connect_fn.lambda_},
        ...
    ])

# 4. Export endpoint
pulumi.export("websocket_url", api.domain)
```

## Testing

### Test Client
Interactive Python client (`test_client.py`) for testing WebSocket APIs:
- Connect with user credentials
- Send broadcast/direct messages
- Receive real-time messages
- JSON and text message support

### Usage
```bash
python test_client.py wss://api-url/stage \
    --user-id user123 \
    --username John
```

## File Structure

```
cloud_foundry/
├── pulumi/
│   ├── websocket_api.py          (New)
│   ├── websocket_function.py     (New)
│   └── connection_store.py       (New)
├── utils/
│   └── websocket_utils.py        (New)
└── __init__.py                   (Updated)

docs/
├── websocket_user_guide.md       (New)
└── websocket_api.md              (New)

examples/
├── readme.md                     (Updated)
└── websocket_chat/               (New)
    ├── __main__.py
    ├── handlers/
    │   ├── connect.py
    │   ├── disconnect.py
    │   ├── send_message.py
    │   └── default.py
    ├── test_client.py
    ├── README.md
    ├── Pulumi.yaml
    └── requirements.txt
```

## Next Steps for Users

1. **Basic Usage**: Follow the example in `examples/websocket_chat/`
2. **Read Documentation**: Start with `docs/websocket_user_guide.md`
3. **Customize**: Extend handlers for application-specific logic
4. **Add Features**: Implement rooms, presence, typing indicators
5. **Secure**: Add Lambda authorizers for production
6. **Optimize**: Monitor CloudWatch metrics and adjust capacity

## Advantages

- **Rapid Development**: Pre-configured components reduce boilerplate
- **Best Practices**: Built-in patterns for connection management
- **Scalable**: Pay-per-request billing and automatic cleanup
- **Secure**: IAM-based permissions and authorizer support
- **Observable**: CloudWatch logging and metrics
- **Maintainable**: Modular design following cloud_foundry patterns

## Compatibility

- **Python**: 3.7+
- **Pulumi**: Compatible with existing cloud_foundry components
- **AWS**: Uses API Gateway V2, Lambda, DynamoDB
- **Runtime**: Tested with Python 3.13 Lambda runtime
