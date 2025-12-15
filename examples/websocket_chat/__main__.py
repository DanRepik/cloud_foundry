"""
WebSocket Chat Example - Infrastructure

This example demonstrates how to create a WebSocket API with:
- Connection and disconnection handlers
- Message broadcasting
- User-specific routing
- Connection state management
"""

import pulumi
from cloud_foundry.pulumi.websocket_api import WebSocketAPI
from cloud_foundry.pulumi.websocket_function import WebSocketFunction
from cloud_foundry.pulumi.connection_store import ConnectionStore
from cloud_foundry.python_archive_builder import PythonArchiveBuilder


# Create the connection store
connection_store = ConnectionStore(
    "chat-connections",
    global_secondary_indexes=[
        {
            "name": "userId-index",
            "hash_key": "userId",
            "projection_type": "ALL",
        }
    ],
)

# Build Lambda deployment packages
connect_archive = PythonArchiveBuilder(
    "connect-handler",
    source_path="handlers/connect.py",
    requirements=["boto3"],
)

disconnect_archive = PythonArchiveBuilder(
    "disconnect-handler",
    source_path="handlers/disconnect.py",
    requirements=["boto3"],
)

send_message_archive = PythonArchiveBuilder(
    "send-message-handler",
    source_path="handlers/send_message.py",
    requirements=["boto3"],
)

default_archive = PythonArchiveBuilder(
    "default-handler",
    source_path="handlers/default.py",
    requirements=["boto3"],
)

# Create WebSocket Lambda functions
connect_function = WebSocketFunction(
    "connect-handler",
    archive_location=connect_archive.archive_path,
    hash=connect_archive.source_code_hash,
    runtime="python3.13",
    handler="connect.handler",
    timeout=30,
    memory_size=256,
    connection_table_arn=connection_store.table_arn,
    connection_table_name=connection_store.table_name,
)

disconnect_function = WebSocketFunction(
    "disconnect-handler",
    archive_location=disconnect_archive.archive_path,
    hash=disconnect_archive.source_code_hash,
    runtime="python3.13",
    handler="disconnect.handler",
    timeout=30,
    memory_size=256,
    connection_table_arn=connection_store.table_arn,
    connection_table_name=connection_store.table_name,
)

send_message_function = WebSocketFunction(
    "send-message-handler",
    archive_location=send_message_archive.archive_path,
    hash=send_message_archive.source_code_hash,
    runtime="python3.13",
    handler="send_message.handler",
    timeout=30,
    memory_size=256,
    connection_table_arn=connection_store.table_arn,
    connection_table_name=connection_store.table_name,
)

default_function = WebSocketFunction(
    "default-handler",
    archive_location=default_archive.archive_path,
    hash=default_archive.source_code_hash,
    runtime="python3.13",
    handler="default.handler",
    timeout=30,
    memory_size=256,
    connection_table_arn=connection_store.table_arn,
    connection_table_name=connection_store.table_name,
)

# Create the WebSocket API
websocket_api = WebSocketAPI(
    "chat-api",
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
    connection_table_arn=connection_store.table_arn,
)

# Update functions with the API endpoint for posting messages
pulumi.export("websocket_url", websocket_api.domain)
pulumi.export("connection_table", connection_store.table_name)
