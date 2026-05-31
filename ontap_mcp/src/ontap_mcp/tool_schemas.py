"""Pydantic schemas for mission-critical diagnostic MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ontap_mcp.tools.ems import DEFAULT_PATTERNS, DEFAULT_SEVERITIES

VALID_SUBSYSTEMS = frozenset({"statit", "wafl.log", "syslog", "nblade", "large_io"})
VALID_PRODUCTS = frozenset({"ONTAP", "GCNV", "OCI_VSA", "ANF", "ALL"})
VALID_DIAGNOSTIC_TYPES = frozenset({
    "cluster_health",
    "network_connections",
    "node_uptime",
    "disk_utilization",
    "volume_summary",
    "perf_snapshot",
})


class FetchEmsLogsInput(BaseModel):
    """Schema: fetch_ems_logs — paginated EMS retrieval via ONTAP REST."""

    cluster_host: str | None = Field(
        default=None,
        description="Cluster management URL; defaults to ONTAP_MGMT_HOST.",
    )
    message_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PATTERNS),
        description="EMS message.name glob patterns.",
    )
    severities: str = Field(
        default=DEFAULT_SEVERITIES,
        description="Comma-separated severity filter.",
    )
    node_name: str | None = Field(default=None, description="Restrict to a single node.")
    start_time: str | None = Field(
        default=None,
        description="ISO-8601 lower bound (inclusive) for event time.",
    )
    end_time: str | None = Field(
        default=None,
        description="ISO-8601 upper bound (inclusive) for event time.",
    )
    max_records: int = Field(default=500, ge=1, le=10_000)
    page_size: int = Field(default=100, ge=10, le=1_000)


class ParseAsupBundleInput(BaseModel):
    """Schema: parse_asup_bundle — selective in-memory ASUP extraction."""

    archive_path: str = Field(..., description="Path to .7z or .tgz ASUP archive.")
    target_subsystems: list[str] = Field(
        ...,
        min_length=1,
        description="Subsystems to extract, e.g. statit, wafl.log, syslog.",
    )
    time_start: str | None = Field(
        default=None,
        description="ISO-8601 window start for log line filtering.",
    )
    time_end: str | None = Field(
        default=None,
        description="ISO-8601 window end for log line filtering.",
    )
    max_summary_events: int = Field(default=100, ge=1, le=1_000)

    @field_validator("target_subsystems")
    @classmethod
    def validate_subsystems(cls, values: list[str]) -> list[str]:
        invalid = [v for v in values if v not in VALID_SUBSYSTEMS]
        if invalid:
            allowed = ", ".join(sorted(VALID_SUBSYSTEMS))
            raise ValueError(f"Invalid target_subsystems {invalid}. Allowed: {allowed}")
        return values


class SearchStorageKbInput(BaseModel):
    """Schema: search_storage_kb — semantic KB lookup."""

    query: str = Field(..., min_length=3, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)
    product_filter: list[Literal["ONTAP", "GCNV", "OCI_VSA", "ANF", "ALL"]] | None = None
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RunActiveDiagnosticInput(BaseModel):
    """Schema: run_active_diagnostic — SSH probe via advanced privilege mode."""

    diagnostic_type: Literal[
        "cluster_health",
        "network_connections",
        "node_uptime",
        "disk_utilization",
        "volume_summary",
        "perf_snapshot",
    ]
    cluster_host: str | None = Field(
        default=None,
        description="SSH target; defaults to ONTAP_SSH_HOST or ONTAP_MGMT_HOST.",
    )
    node_name: str | None = Field(
        default=None,
        description="Required for node-scoped diagnostics (node_uptime, perf_snapshot).",
    )
    connect_timeout_sec: int = Field(default=15, ge=5, le=60)
    command_timeout_sec: int = Field(default=30, ge=5, le=120)
