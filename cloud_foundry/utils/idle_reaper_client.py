"""Runtime-side client for cloud_foundry's idle-ESM-reaper "enable" event.

Companion to cloud_foundry.pulumi.idle_reaper.attach_idle_reaper -- unlike
that module (which authors Pulumi infrastructure at `pulumi up` time), this
one runs inside whatever already-deployed producer/ingestion code sends
messages into a reaper-managed queue. This module itself only needs boto3,
but importing it as `cloud_foundry.utils.idle_reaper_client` still runs
`cloud_foundry/__init__.py` first (normal Python package behavior), which
pulls in pulumi/pulumi-aws as transitive dependencies of the `cloud-foundry`
package regardless. A producer that wants to avoid carrying those into a
lightweight Lambda can inline the few lines of `request_mapping_enable`
below instead of depending on `cloud-foundry` for just this.

A producer that wants the shared reaper to keep its queue's mapping alive
calls `request_mapping_enable(queue_url)` before sending. It never needs to
know the event source mapping's UUID, the reaper's function/role names, or
any Pulumi-side resource naming scheme -- only the queue URL it already has
to know to call SendMessage in the first place.
"""

import json
from typing import Optional

import boto3


def request_mapping_enable(
    queue_url: str,
    *,
    event_bus_name: str = "default",
    region_name: Optional[str] = None,
) -> None:
    """Ask the shared idle-ESM-reaper to re-enable the mapping for `queue_url`.

    Fire-and-forget: puts a custom event on the given EventBridge bus. Any
    `attach_idle_reaper` consumer whose queue matches `queue_url` picks it
    up via its own scoped EventRule and re-enables its own mapping --
    nothing here needs to know which consumer that is, or whether one
    exists at all (an unmatched event is simply dropped by EventBridge, so
    calling this for a queue that isn't reaper-managed is a harmless no-op).

    Args:
        queue_url: The SQS queue URL the caller is about to send messages
            to -- must match the `queue_url` the mapping owner's
            `attach_idle_reaper()` call was scoped to.
        event_bus_name: EventBridge bus to publish to. Must match the
            `event_bus_name` the mapping owner passed to
            `attach_idle_reaper()` -- both default to the account's
            "default" bus.
        region_name: AWS region for the EventBridge client, if not picked
            up from the caller's ambient environment/credentials.
    """
    events = boto3.client("events", region_name=region_name)
    events.put_events(
        Entries=[
            {
                "EventBusName": event_bus_name,
                "Source": "cloud_foundry.idle_reaper",
                "DetailType": "EnableMapping",
                "Detail": json.dumps({"queue_url": queue_url}),
            }
        ]
    )
