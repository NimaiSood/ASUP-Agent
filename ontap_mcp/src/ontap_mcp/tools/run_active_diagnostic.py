"""Active SSH diagnostics against ONTAP advanced privilege CLI."""

from __future__ import annotations

import logging
import os
import socket
import time
from typing import Any

import paramiko

from ontap_mcp.tool_schemas import RunActiveDiagnosticInput

logger = logging.getLogger(__name__)

# Read-only, allowlisted CLI probes mapped by diagnostic_type.
_DIAGNOSTIC_COMMANDS: dict[str, list[str]] = {
    "cluster_health": [
        "system health show -instance",
    ],
    "network_connections": [
        "network connections active -max 100",
    ],
    "node_uptime": [
        "system node run -node {node} -command uptime",
    ],
    "disk_utilization": [
        "storage disk show -fields node,busy,raid_state,type -max 50",
    ],
    "volume_summary": [
        "volume show -fields state,size,used,available,percent-used -max 30",
    ],
    "perf_snapshot": [
        "statistics show-periodic -node {node} -interval 1 -iterations 3",
    ],
}

_PRIVilege_COMMANDS = [
    "set -privilege advanced -confirmations off",
]


def _resolve_ssh_host(cluster_host: str | None) -> str:
    host = cluster_host or os.environ.get("ONTAP_SSH_HOST") or os.environ.get("ONTAP_MGMT_HOST", "")
    if not host:
        raise ValueError("cluster_host required or set ONTAP_SSH_HOST / ONTAP_MGMT_HOST")
    host = host.replace("https://", "").replace("http://", "").split("/")[0]
    return host


def _ssh_credentials() -> tuple[str, str]:
    username = os.environ.get("ONTAP_SSH_USERNAME") or os.environ["ONTAP_USERNAME"]
    password = os.environ.get("ONTAP_SSH_PASSWORD") or os.environ["ONTAP_PASSWORD"]
    return username, password


def _resolve_commands(params: RunActiveDiagnosticInput) -> list[str]:
    templates = _DIAGNOSTIC_COMMANDS.get(params.diagnostic_type)
    if not templates:
        allowed = ", ".join(sorted(_DIAGNOSTIC_COMMANDS))
        raise ValueError(f"Unknown diagnostic_type. Allowed: {allowed}")

    node_required = params.diagnostic_type in ("node_uptime", "perf_snapshot")
    if node_required and not params.node_name:
        raise ValueError(f"node_name is required for diagnostic_type={params.diagnostic_type!r}")

    node = params.node_name or ""
    return [tpl.format(node=node) for tpl in templates]


def _read_until_idle(channel: paramiko.Channel, idle_sec: float, max_wait_sec: float) -> str:
    deadline = time.monotonic() + max_wait_sec
    last_data = time.monotonic()
    chunks: list[str] = []

    while time.monotonic() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(65535).decode("utf-8", errors="replace")
            chunks.append(chunk)
            last_data = time.monotonic()
        elif time.monotonic() - last_data >= idle_sec:
            break
        else:
            time.sleep(0.1)

    return "".join(chunks)


def _run_shell_commands(
    client: paramiko.SSHClient,
    commands: list[str],
    *,
    command_timeout_sec: int,
) -> list[dict[str, str]]:
    channel = client.invoke_shell(width=220)
    channel.settimeout(command_timeout_sec)
    outputs: list[dict[str, str]] = []

    try:
        _read_until_idle(channel, idle_sec=1.0, max_wait_sec=5.0)

        for cmd in _PRIVilege_COMMANDS + commands:
            logger.info("SSH exec: %s", cmd)
            channel.send(cmd + "\n")
            text = _read_until_idle(
                channel,
                idle_sec=1.5,
                max_wait_sec=float(command_timeout_sec),
            )
            outputs.append({"command": cmd, "output": text[-8000:]})
    finally:
        channel.close()

    return outputs


def run_active_diagnostic(params: RunActiveDiagnosticInput) -> dict[str, Any]:
    """Establish SSH session and run allowlisted diagnostic commands."""
    host = _resolve_ssh_host(params.cluster_host)
    username, password = _ssh_credentials()
    commands = _resolve_commands(params)
    port = int(os.environ.get("ONTAP_SSH_PORT", "22"))

    logger.info(
        "Active diagnostic type=%s host=%s node=%s timeout=%ds",
        params.diagnostic_type,
        host,
        params.node_name,
        params.command_timeout_sec,
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    started = time.monotonic()
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=params.connect_timeout_sec,
            banner_timeout=params.connect_timeout_sec,
            auth_timeout=params.connect_timeout_sec,
            look_for_keys=False,
            allow_agent=False,
        )
    except (paramiko.SSHException, socket.timeout, OSError) as exc:
        logger.exception("SSH connection failed to %s:%d", host, port)
        return {
            "status": "error",
            "diagnostic_type": params.diagnostic_type,
            "cluster_host": host,
            "error": f"SSH connection failed: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 2),
        }

    try:
        command_results = _run_shell_commands(
            client,
            commands,
            command_timeout_sec=params.command_timeout_sec,
        )
    except (paramiko.SSHException, socket.timeout, OSError) as exc:
        logger.exception("SSH command execution failed")
        return {
            "status": "error",
            "diagnostic_type": params.diagnostic_type,
            "cluster_host": host,
            "error": f"Command execution failed: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 2),
        }
    finally:
        client.close()

    elapsed = round(time.monotonic() - started, 2)
    logger.info("Active diagnostic complete in %.2fs", elapsed)
    return {
        "status": "ok",
        "diagnostic_type": params.diagnostic_type,
        "cluster_host": host,
        "node_name": params.node_name,
        "commands": command_results,
        "elapsed_sec": elapsed,
    }
