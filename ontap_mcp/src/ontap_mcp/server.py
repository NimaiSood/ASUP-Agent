"""ONTAP MCP Server — EMS, volumes, AutoSupport, active diagnostics."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from ontap_mcp.client import OntapClient
from ontap_mcp.guardrails import Guardrails
from ontap_mcp.tool_schemas import (
    FetchEmsLogsInput,
    ParseAsupBundleInput,
    RunActiveDiagnosticInput,
    SearchStorageKbInput,
)
from ontap_mcp.tools.autosupport import invoke_autosupport, list_autosupport_messages
from ontap_mcp.tools.ems import DEFAULT_PATTERNS, get_ems_events
from ontap_mcp.tools.fetch_ems_logs import fetch_ems_logs
from ontap_mcp.tools.parse_asup_bundle import parse_asup_bundle
from ontap_mcp.tools.run_active_diagnostic import run_active_diagnostic
from ontap_mcp.tools.search_storage_kb import search_storage_kb
from ontap_mcp.tools.volumes import get_volume_stats

logging.basicConfig(
    level=os.environ.get("ONTAP_MCP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ontap_mcp")

mcp = FastMCP("ontap-mcp")
_guardrails = Guardrails()


def _client() -> OntapClient:
    return OntapClient()


def _parse_asup(archive_path: str, output_dir: str | None) -> dict[str, Any]:
    """Import ASUP parser from sibling package if installed."""
    try:
        from asup_agent.parser.archive import parse_archive

        return parse_archive(archive_path, output_dir=output_dir)
    except ImportError:
        return {
            "error": "asup_agent not installed. Run: pip install -e ../asup_agent",
            "archive_path": archive_path,
        }


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


def _validation_error(tool: str, exc: ValidationError) -> str:
    logger.warning("Schema validation failed for %s: %s", tool, exc)
    return _json_result({"error": "schema_validation_failed", "tool": tool, "details": exc.errors()})


@mcp.tool()
def get_ems_events_tool(
    message_patterns: list[str] | None = None,
    severities: str = "emergency,alert,error,warning",
    node_name: str | None = None,
    max_records: int = 500,
) -> str:
    """Retrieve filtered EMS events for RCA. Default patterns cover WAFL, nblade, stat storms, large IO."""
    with _client() as client:
        data = get_ems_events(
            client,
            message_patterns=message_patterns,
            severities=severities,
            node_name=node_name,
            max_records=max_records,
        )
    return _json_result(data)


@mcp.tool()
def get_volume_stats_tool(
    svm_name: str | None = None,
    volume_name: str | None = None,
    max_records: int = 100,
) -> str:
    """Retrieve volume statistics and space info for performance correlation."""
    with _client() as client:
        data = get_volume_stats(client, svm_name=svm_name, volume_name=volume_name, max_records=max_records)
    return _json_result(data)


@mcp.tool()
def list_autosupport_messages_tool(
    node_name: str | None = None,
    max_records: int = 50,
) -> str:
    """List AutoSupport message history from the cluster."""
    with _client() as client:
        data = list_autosupport_messages(client, node_name=node_name, max_records=max_records)
    return _json_result(data)


@mcp.tool()
def invoke_autosupport_tool(
    node_name: str | None = None,
    message: str = "ASUP Agent on-demand invoke",
) -> str:
    """Trigger on-demand AutoSupport. Requires ONTAP_ALLOW_MUTATIONS=true. Rate-limited."""
    with _client() as client:
        data = invoke_autosupport(client, _guardrails, node_name=node_name, message=message)
    return _json_result(data)


@mcp.tool()
def parse_asup_archive_tool(
    archive_path: str,
    output_dir: str | None = None,
) -> str:
    """Decrypt and parse a local AutoSupport archive. Extracts syslog, wafl.log, statit."""
    path = Path(archive_path).expanduser().resolve()
    if not path.exists():
        return _json_result({"error": f"Archive not found: {path}"})
    result = _parse_asup(str(path), output_dir)
    return _json_result(result)


@mcp.tool()
def fetch_ems_logs_tool(
    cluster_host: str | None = None,
    message_patterns: list[str] | None = None,
    severities: str = "emergency,alert,error,warning",
    node_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    max_records: int = 500,
    page_size: int = 100,
) -> str:
    """Fetch EMS logs via ONTAP REST with pagination and rate-limit backoff."""
    try:
        params = FetchEmsLogsInput(
            cluster_host=cluster_host,
            message_patterns=message_patterns or list(DEFAULT_PATTERNS),
            severities=severities,
            node_name=node_name,
            start_time=start_time,
            end_time=end_time,
            max_records=max_records,
            page_size=page_size,
        )
    except ValidationError as exc:
        return _validation_error("fetch_ems_logs", exc)

    logger.info("Tool fetch_ems_logs invoked node=%s window=%s..%s", node_name, start_time, end_time)
    try:
        data = fetch_ems_logs(params)
        return _json_result(data)
    except Exception as exc:
        logger.exception("fetch_ems_logs failed")
        return _json_result({"error": str(exc), "tool": "fetch_ems_logs"})


@mcp.tool()
def parse_asup_bundle_tool(
    archive_path: str,
    target_subsystems: list[str],
    time_start: str | None = None,
    time_end: str | None = None,
    max_summary_events: int = 100,
) -> str:
    """Parse ASUP .7z/.tgz archive; extract target subsystems and return structured summaries."""
    try:
        params = ParseAsupBundleInput(
            archive_path=archive_path,
            target_subsystems=target_subsystems,
            time_start=time_start,
            time_end=time_end,
            max_summary_events=max_summary_events,
        )
    except ValidationError as exc:
        return _validation_error("parse_asup_bundle", exc)

    logger.info("Tool parse_asup_bundle invoked path=%s subsystems=%s", archive_path, target_subsystems)
    try:
        data = parse_asup_bundle(params)
        return _json_result(data)
    except FileNotFoundError as exc:
        return _json_result({"error": str(exc), "tool": "parse_asup_bundle"})
    except Exception as exc:
        logger.exception("parse_asup_bundle failed")
        return _json_result({"error": str(exc), "tool": "parse_asup_bundle"})


@mcp.tool()
def search_storage_kb_tool(
    query: str,
    top_k: int = 5,
    product_filter: list[str] | None = None,
    min_score: float = 0.0,
) -> str:
    """Semantic search across storage knowledge-base articles (ONTAP, GCNV, OCI VSA, ANF)."""
    try:
        params = SearchStorageKbInput(
            query=query,
            top_k=top_k,
            product_filter=product_filter,
            min_score=min_score,
        )
    except ValidationError as exc:
        return _validation_error("search_storage_kb", exc)

    logger.info("Tool search_storage_kb invoked query=%r", query[:80])
    data = search_storage_kb(params)
    return _json_result(data)


@mcp.tool()
def run_active_diagnostic_tool(
    diagnostic_type: str,
    cluster_host: str | None = None,
    node_name: str | None = None,
    connect_timeout_sec: int = 15,
    command_timeout_sec: int = 30,
) -> str:
    """Run allowlisted SSH diagnostic probe in ONTAP advanced privilege mode."""
    try:
        params = RunActiveDiagnosticInput(
            diagnostic_type=diagnostic_type,
            cluster_host=cluster_host,
            node_name=node_name,
            connect_timeout_sec=connect_timeout_sec,
            command_timeout_sec=command_timeout_sec,
        )
    except ValidationError as exc:
        return _validation_error("run_active_diagnostic", exc)

    logger.info(
        "Tool run_active_diagnostic invoked type=%s host=%s node=%s",
        diagnostic_type,
        cluster_host,
        node_name,
    )
    data = run_active_diagnostic(params)
    return _json_result(data)


def main() -> None:
    required = ("ONTAP_MGMT_HOST", "ONTAP_USERNAME", "ONTAP_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    logger.info("Starting ONTAP MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
