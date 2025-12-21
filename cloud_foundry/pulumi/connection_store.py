# connection_store.py

import pulumi
import pulumi_aws as aws
from cloud_foundry.utils.logger import logger

log = logger(__name__)


class ConnectionStore(pulumi.ComponentResource):
    """
    A DynamoDB table for managing WebSocket connections.

    This component creates a DynamoDB table optimized for storing and
    querying WebSocket connection information including:
    - Connection IDs (primary key)
    - User identification and metadata
    - Connection timestamps
    - Custom routing attributes
    - TTL for automatic cleanup of stale connections
    """

    table: aws.dynamodb.Table
    table_name: pulumi.Output[str]
    table_arn: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        *,
        ttl_attribute: str = "ttl",
        ttl_enabled: bool = True,
        read_capacity: int = 5,
        write_capacity: int = 5,
        billing_mode: str = "PAY_PER_REQUEST",
        global_secondary_indexes: list[dict] = None,
        opts=None,
    ):
        """
        Initialize the ConnectionStore component.

        Args:
            name (str): Name of the connection store
            ttl_attribute (str): Name of the TTL attribute (default: "ttl")
            ttl_enabled (bool): Enable TTL for automatic cleanup
                (default: True)
            read_capacity (int): Provisioned read capacity units
                (only used if billing_mode is PROVISIONED)
            write_capacity (int): Provisioned write capacity units
                (only used if billing_mode is PROVISIONED)
            billing_mode (str): Billing mode - "PAY_PER_REQUEST" or
                "PROVISIONED" (default: "PAY_PER_REQUEST")
            global_secondary_indexes (list[dict]): Additional GSIs for
                querying connections by custom attributes. Each dict should
                have:
                - name (str): Index name
                - hash_key (str): Partition key attribute
                - range_key (str, optional): Sort key attribute
                - projection_type (str): ALL, KEYS_ONLY, or INCLUDE
                - non_key_attributes (list, optional): For INCLUDE projection
            opts (pulumi.ResourceOptions): Pulumi resource options
        """
        super().__init__("cloud_foundry:websocket:ConnectionStore", name, None, opts)
        self.name = name
        self.ttl_attribute = ttl_attribute
        self.ttl_enabled = ttl_enabled
        self.global_secondary_indexes = global_secondary_indexes or []

        # Create the DynamoDB table
        self.table = self._create_table(billing_mode, read_capacity, write_capacity)
        self.table_name = self.table.name
        self.table_arn = self.table.arn

        # Register outputs
        self.register_outputs(
            {
                "table_name": self.table_name,
                "table_arn": self.table_arn,
            }
        )

    def _create_table(self, billing_mode: str, read_capacity: int, write_capacity: int):
        """
        Create the DynamoDB table for connection storage.

        Args:
            billing_mode: Billing mode for the table
            read_capacity: Provisioned read capacity
            write_capacity: Provisioned write capacity

        Returns:
            aws.dynamodb.Table: The created table
        """
        log.info("Creating connection store table: %s", self.name)

        table_name = f"{pulumi.get_project()}-{pulumi.get_stack()}-{self.name}"

        # Define base attributes
        attributes = [
            aws.dynamodb.TableAttributeArgs(
                name="connectionId",
                type="S",
            ),
        ]

        # Add attributes for GSIs
        for gsi in self.global_secondary_indexes:
            if gsi.get("hash_key") and not any(
                attr.name == gsi["hash_key"] for attr in attributes
            ):
                attributes.append(
                    aws.dynamodb.TableAttributeArgs(
                        name=gsi["hash_key"],
                        type=gsi.get("hash_key_type", "S"),
                    )
                )
            if gsi.get("range_key") and not any(
                attr.name == gsi["range_key"] for attr in attributes
            ):
                attributes.append(
                    aws.dynamodb.TableAttributeArgs(
                        name=gsi["range_key"],
                        type=gsi.get("range_key_type", "S"),
                    )
                )

        # Prepare GSI configurations
        gsi_configs = []
        for gsi in self.global_secondary_indexes:
            gsi_config = aws.dynamodb.TableGlobalSecondaryIndexArgs(
                name=gsi["name"],
                hash_key=gsi["hash_key"],
                projection_type=gsi.get("projection_type", "ALL"),
            )

            if gsi.get("range_key"):
                gsi_config.range_key = gsi["range_key"]

            if gsi.get("projection_type") == "INCLUDE":
                gsi_config.non_key_attributes = gsi.get("non_key_attributes", [])

            if billing_mode == "PROVISIONED":
                gsi_config.read_capacity = gsi.get("read_capacity", 5)
                gsi_config.write_capacity = gsi.get("write_capacity", 5)

            gsi_configs.append(gsi_config)

        # Create table configuration
        table_config = {
            "name": table_name,
            "hash_key": "connectionId",
            "attributes": attributes,
            "billing_mode": billing_mode,
            "global_secondary_indexes": gsi_configs if gsi_configs else None,
        }

        # Add capacity settings for PROVISIONED mode
        if billing_mode == "PROVISIONED":
            table_config["read_capacity"] = read_capacity
            table_config["write_capacity"] = write_capacity

        # Add TTL configuration if enabled
        if self.ttl_enabled:
            table_config["ttl"] = aws.dynamodb.TableTtlArgs(
                attribute_name=self.ttl_attribute,
                enabled=True,
            )

        # Create the table
        table = aws.dynamodb.Table(
            f"{self.name}-table",
            **table_config,
            opts=pulumi.ResourceOptions(parent=self),
        )

        return table
