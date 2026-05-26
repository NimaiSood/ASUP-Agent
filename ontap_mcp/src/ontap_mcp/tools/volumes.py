"""Volume statistics retrieval."""

from __future__ import annotations

from typing import Any

from ontap_mcp.client import OntapClient


def get_volume_stats(
    client: OntapClient,
    *,
    svm_name: str | None = None,
    volume_name: str | None = None,
    max_records: int = 100,
) -> dict[str, Any]:
    """Retrieve volume list with performance-relevant fields."""
    params: dict[str, Any] = {
        "fields": "name,uuid,svm,state,type,space,statistics",
        "max_records": max_records,
    }
    if svm_name:
        params["svm.name"] = svm_name
    if volume_name:
        params["name"] = volume_name

    return client.get("/api/storage/volumes", params=params)
