"""AutoSupport message operations."""

from __future__ import annotations

from typing import Any

from ontap_mcp.client import OntapClient
from ontap_mcp.guardrails import Guardrails


def list_autosupport_messages(
    client: OntapClient,
    *,
    node_name: str | None = None,
    max_records: int = 50,
) -> dict[str, Any]:
    """Retrieve AutoSupport message history."""
    params: dict[str, Any] = {
        "max_records": max_records,
        "order_by": "date desc",
        "fields": "index,date,node,subject,type,state",
    }
    if node_name:
        params["node.name"] = node_name
    return client.get("/api/support/autosupport/messages", params=params)


def invoke_autosupport(
    client: OntapClient,
    guardrails: Guardrails,
    *,
    node_name: str | None = None,
    message: str = "ASUP Agent on-demand invoke",
    type_: str = "all",
) -> dict[str, Any]:
    """Trigger on-demand AutoSupport (guardrailed, rate-limited)."""
    node_key = node_name or "__cluster__"
    guardrails.check_autosupport_invoke(node_key)

    body: dict[str, Any] = {
        "type": type_,
        "message": message,
    }
    if node_name:
        body["node"] = {"name": node_name}

    return client.post("/api/support/autosupport/messages", body)
