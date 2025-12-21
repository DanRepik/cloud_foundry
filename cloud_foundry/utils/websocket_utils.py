# websocket_utils.py

"""
WebSocket utility functions for Lambda handlers.

This module provides helper functions for WebSocket Lambda handlers to:
- Manage connection lifecycle (store, retrieve, delete connections)
- Send messages to individual connections
- Broadcast messages to multiple connections
- Query connections by attributes
"""

import json
import os
from typing import Optional, Any
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError


def get_connection_table():
    """
    Get the DynamoDB table for connection management.

    Returns:
        boto3.resource.Table: DynamoDB table resource

    Raises:
        ValueError: If CONNECTION_TABLE_NAME is not set
    """
    table_name = os.environ.get("CONNECTION_TABLE_NAME")
    if not table_name:
        raise ValueError("CONNECTION_TABLE_NAME environment variable not set")

    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def get_api_gateway_client():
    """
    Get the API Gateway Management API client.

    Returns:
        boto3.client: API Gateway Management API client

    Raises:
        ValueError: If WEBSOCKET_API_ENDPOINT is not set
    """
    endpoint = os.environ.get("WEBSOCKET_API_ENDPOINT")
    if not endpoint:
        raise ValueError("WEBSOCKET_API_ENDPOINT environment variable not set")

    # Extract the endpoint URL from the full WebSocket URL
    # Expected format: wss://xxxxx.execute-api.region.amazonaws.com/stage
    if endpoint.startswith("wss://"):
        endpoint = endpoint.replace("wss://", "https://")
    elif endpoint.startswith("ws://"):
        endpoint = endpoint.replace("ws://", "http://")

    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)


def store_connection(
    connection_id: str,
    user_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    ttl_hours: int = 24,
) -> dict:
    """
    Store a WebSocket connection in DynamoDB.

    Args:
        connection_id (str): The WebSocket connection ID
        user_id (Optional[str]): User identifier for this connection
        metadata (Optional[dict]): Additional metadata to store
        ttl_hours (int): Hours until the connection record expires
            (default: 24)

    Returns:
        dict: The stored connection item

    Raises:
        ClientError: If DynamoDB operation fails
    """
    table = get_connection_table()

    # Calculate TTL timestamp
    ttl = int((datetime.now() + timedelta(hours=ttl_hours)).timestamp())

    item = {
        "connectionId": connection_id,
        "connectedAt": datetime.now().isoformat(),
        "ttl": ttl,
    }

    if user_id:
        item["userId"] = user_id

    if metadata:
        item["metadata"] = metadata

    table.put_item(Item=item)
    return item


def get_connection(connection_id: str) -> Optional[dict]:
    """
    Retrieve a connection from DynamoDB.

    Args:
        connection_id (str): The WebSocket connection ID

    Returns:
        Optional[dict]: The connection item or None if not found
    """
    table = get_connection_table()

    try:
        response = table.get_item(Key={"connectionId": connection_id})
        return response.get("Item")
    except ClientError:
        return None


def delete_connection(connection_id: str) -> bool:
    """
    Delete a connection from DynamoDB.

    Args:
        connection_id (str): The WebSocket connection ID

    Returns:
        bool: True if deletion was successful
    """
    table = get_connection_table()

    try:
        table.delete_item(Key={"connectionId": connection_id})
        return True
    except ClientError:
        return False


def update_connection(
    connection_id: str,
    updates: dict,
) -> Optional[dict]:
    """
    Update a connection's attributes in DynamoDB.

    Args:
        connection_id (str): The WebSocket connection ID
        updates (dict): Dictionary of attributes to update

    Returns:
        Optional[dict]: The updated connection item or None if failed
    """
    table = get_connection_table()

    # Build update expression
    update_expr_parts = []
    expr_attr_names = {}
    expr_attr_values = {}

    for key, value in updates.items():
        attr_name = f"#{key}"
        attr_value = f":{key}"
        update_expr_parts.append(f"{attr_name} = {attr_value}")
        expr_attr_names[attr_name] = key
        expr_attr_values[attr_value] = value

    update_expression = "SET " + ", ".join(update_expr_parts)

    try:
        response = table.update_item(
            Key={"connectionId": connection_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
    except ClientError:
        return None


def send_message(
    connection_id: str,
    data: Any,
) -> bool:
    """
    Send a message to a specific WebSocket connection.

    Args:
        connection_id (str): The WebSocket connection ID
        data (Any): Data to send (will be JSON-encoded if not a string)

    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    client = get_api_gateway_client()

    # Convert data to bytes
    if isinstance(data, str):
        message = data.encode("utf-8")
    elif isinstance(data, bytes):
        message = data
    else:
        message = json.dumps(data).encode("utf-8")

    try:
        client.post_to_connection(ConnectionId=connection_id, Data=message)
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "GoneException":
            # Connection is no longer available, clean it up
            delete_connection(connection_id)
        return False


def broadcast_message(
    data: Any,
    filter_fn: Optional[callable] = None,
) -> dict:
    """
    Broadcast a message to all (or filtered) connections.

    Args:
        data (Any): Data to send (will be JSON-encoded if not a string)
        filter_fn (Optional[callable]): Function to filter connections.
            Should accept a connection dict and return bool.

    Returns:
        dict: Statistics about the broadcast
            - sent: Number of messages sent successfully
            - failed: Number of failed sends
            - filtered: Number of connections filtered out
    """
    table = get_connection_table()

    stats = {"sent": 0, "failed": 0, "filtered": 0}

    # Scan all connections
    response = table.scan()
    connections = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        connections.extend(response.get("Items", []))

    # Send to each connection
    for connection in connections:
        connection_id = connection["connectionId"]

        # Apply filter if provided
        if filter_fn and not filter_fn(connection):
            stats["filtered"] += 1
            continue

        # Send message
        if send_message(connection_id, data):
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    return stats


def get_connections_by_user(user_id: str) -> list[dict]:
    """
    Get all connections for a specific user.

    Note: This requires a GSI on userId attribute.

    Args:
        user_id (str): The user identifier

    Returns:
        list[dict]: List of connection items for the user
    """
    table = get_connection_table()

    try:
        response = table.query(
            IndexName="userId-index",  # GSI name - must be configured
            KeyConditionExpression="userId = :userId",
            ExpressionAttributeValues={":userId": user_id},
        )
        return response.get("Items", [])
    except ClientError:
        return []


def send_to_user(user_id: str, data: Any) -> dict:
    """
    Send a message to all connections belonging to a user.

    Args:
        user_id (str): The user identifier
        data (Any): Data to send

    Returns:
        dict: Statistics about sends (sent, failed)
    """
    connections = get_connections_by_user(user_id)
    stats = {"sent": 0, "failed": 0}

    for connection in connections:
        connection_id = connection["connectionId"]
        if send_message(connection_id, data):
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    return stats


def create_response(status_code: int, body: Any = None) -> dict:
    """
    Create a standard WebSocket Lambda response.

    Args:
        status_code (int): HTTP status code
        body (Any): Response body (optional)

    Returns:
        dict: Lambda response object
    """
    response = {"statusCode": status_code}

    if body is not None:
        if isinstance(body, str):
            response["body"] = body
        else:
            response["body"] = json.dumps(body)

    return response
