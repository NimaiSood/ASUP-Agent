"""ONTAP MCP Server — EMS, volumes, AutoSupport."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ontap_mcp.client import OntapClient
from ontap_mcp.guardrails import Guardrails
from ontap_mcp.tools.autosupport import invoke_autosupport, list_autosupport_messages
from ontap_mcp.tools.ems import get_ems_events
from ontap_mcp.tools.volumes import get_volume_stats

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
  return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_volume_stats_tool(
    svm_name: str | None = None,
    volume_name: str | None = None,
    max_records: int = 100,
) -> str:
  """Retrieve volume statistics and space info for performance correlation."""
  with _client() as client:
    data = get_volume_stats(client, svm_name=svm_name, volume_name=volume_name, max_records=max_records)
  return json.dumps(data, indent=2, default=str)


@mcp.tool()
def list_autosupport_messages_tool(
    node_name: str | None = None,
    max_records: int = 50,
) -> str:
  """List AutoSupport message history from the cluster."""
  with _client() as client:
    data = list_autosupport_messages(client, node_name=node_name, max_records=max_records)
  return json.dumps(data, indent=2, default=str)


@mcp.tool()
def invoke_autosupport_tool(
    node_name: str | None = None,
    message: str = "ASUP Agent on-demand invoke",
) -> str:
  """Trigger on-demand AutoSupport. Requires ONTAP_ALLOW_MUTATIONS=true. Rate-limited."""
  with _client() as client:
    data = invoke_autosupport(client, _guardrails, node_name=node_name, message=message)
  return json.dumps(data, indent=2, default=str)


@mcp.tool()
def parse_asup_archive_tool(
    archive_path: str,
    output_dir: str | None = None,
) -> str:
  """Decrypt and parse a local AutoSupport archive. Extracts syslog, wafl.log, statit."""
  path = Path(archive_path).expanduser().resolve()
  if not path.exists():
    return json.dumps({"error": f"Archive not found: {path}"})
  result = _parse_asup(str(path), output_dir)
  return json.dumps(result, indent=2, default=str)


def main() -> None:
  required = ("ONTAP_MGMT_HOST", "ONTAP_USERNAME", "ONTAP_PASSWORD")
  missing = [k for k in required if not os.environ.get(k)]
  if missing:
    print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
  mcp.run()


if __name__ == "__main__":
  main()
