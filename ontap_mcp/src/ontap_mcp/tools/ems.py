"""EMS event retrieval and filtering."""

from __future__ import annotations

from typing import Any

from ontap_mcp.client import OntapClient

DEFAULT_PATTERNS = [
    "wafl.*",
    "nblade.*",
    "stat.*",
    "flexgroup.*",
    "large_io.*",
    "resource.*",
    "cpu.*",
    "nvram.*",
]

DEFAULT_SEVERITIES = "emergency,alert,error,warning"


def get_ems_events(
    client: OntapClient,
    *,
    message_patterns: list[str] | None = None,
    severities: str = DEFAULT_SEVERITIES,
    node_name: str | None = None,
    max_records: int = 500,
    order_by: str = "time desc",
) -> dict[str, Any]:
    """Retrieve filtered EMS events from ONTAP."""
    patterns = message_patterns or DEFAULT_PATTERNS
    params: dict[str, Any] = {
        "max_records": max_records,
        "order_by": order_by,
        "message.severity": severities,
        "fields": "index,time,log_message,message,node,parameters,source",
    }
    if node_name:
        params["node.name"] = node_name

    # ONTAP REST supports one message.name filter; fetch per pattern and merge.
    all_records: list[dict[str, Any]] = []
    for pattern in patterns:
        p = {**params, "message.name": pattern}
        try:
            data = client.get("/api/support/ems/events", params=p)
            all_records.extend(data.get("records", []))
        except Exception:
            continue

    # Deduplicate by node + index
    seen: set[tuple[str, int]] = set()
    unique: list[dict[str, Any]] = []
    for rec in all_records:
        key = (rec.get("node", {}).get("name", ""), rec.get("index", 0))
        if key not in seen:
            seen.add(key)
            unique.append(rec)

    unique.sort(key=lambda r: r.get("time", ""), reverse=True)
    return {"num_records": len(unique), "records": unique[:max_records]}
