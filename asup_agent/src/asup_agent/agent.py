"""Autonomous RCA agent runner — ReAct loop over telemetry, EMS, and ASUP."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asup_agent.rca.workflow import IncidentContext, run_rca

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "demo"


@dataclass
class AgentConfig:
    cluster: str = "demo-cluster-01"
    window_start: str = "2026-05-20T14:00:00Z"
    window_end: str = "2026-05-20T15:30:00Z"
    symptom: str = "NFS read latency spike on FlexGroup vol_fg01"
    svm: str = "svm_nfs01"
    volumes: list[str] | None = None
    asup_path: str | None = None
    use_live: bool = False
    live_ems: bool = False


def _log(step: int, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] Step {step}: {msg}", file=sys.stderr)


def _try_live_ems() -> dict[str, Any] | None:
    if not all(os.environ.get(k) for k in ("ONTAP_MGMT_HOST", "ONTAP_USERNAME", "ONTAP_PASSWORD")):
        return None
    try:
        from ontap_mcp.client import OntapClient
        from ontap_mcp.tools.ems import get_ems_events

        with OntapClient() as client:
            return get_ems_events(client, max_records=500)
    except Exception as exc:
        _log(2, f"Live EMS failed ({exc}), using fixtures")
        return None


def _try_live_volumes(svm: str) -> dict[str, Any] | None:
    if not all(os.environ.get(k) for k in ("ONTAP_MGMT_HOST", "ONTAP_USERNAME", "ONTAP_PASSWORD")):
        return None
    try:
        from ontap_mcp.client import OntapClient
        from ontap_mcp.tools.volumes import get_volume_stats

        with OntapClient() as client:
            return get_volume_stats(client, svm_name=svm)
    except Exception:
        return None


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    return json.loads(path.read_text())


def _load_harvest_anomalies() -> list[dict[str, Any]]:
    if os.environ.get("HARVEST_TSDB_URL"):
        _log(1, "HARVEST_TSDB_URL set but Harvest MCP not wired in this session — using fixture anomalies")
    return _load_fixture("harvest_anomalies.json")


def _parse_asup(path: str | None) -> dict[str, Any] | None:
    if path and Path(path).exists():
        from asup_agent.parser.archive import parse_archive

        return parse_archive(path)
    fixture = FIXTURES / "asup_summary.json"
    if fixture.exists():
        return json.loads(fixture.read_text())
    return None


def run_agent(config: AgentConfig | None = None) -> dict[str, Any]:
    cfg = config or AgentConfig()
    volumes = cfg.volumes or ["vol_fg01"]

    _log(1, "Telemetry ingestion — loading Harvest metric anomalies")
    harvest_anomalies = _load_harvest_anomalies()
    _log(1, f"  → {len(harvest_anomalies)} anomaly points loaded")

    _log(2, "Log extraction — querying EMS events")
    ems_data = _try_live_ems() if cfg.use_live else None
    if ems_data is None:
        if cfg.use_live:
            _log(2, "  → Live EMS unavailable, falling back to fixtures")
        ems_data = _load_fixture("ems_events.json")
        _log(2, f"  → {ems_data.get('num_records', 0)} EMS events (fixture)")
    else:
        cfg.live_ems = True
        _log(2, f"  → {ems_data.get('num_records', 0)} EMS events (live)")

    vol_stats = _try_live_volumes(cfg.svm) if cfg.use_live else None
    if vol_stats:
        _log(2, f"  → {vol_stats.get('num_records', 0)} volumes retrieved (live)")

    _log(3, "ASUP retrieval & parsing")
    asup_summary = _parse_asup(cfg.asup_path)
    if asup_summary:
        counts = asup_summary.get("artifact_counts") or asup_summary.get("syslog_events", {}).get("category_counts", {})
        _log(3, f"  → ASUP artifacts parsed: {counts}")

    _log(4, "Data correlation — building timeline")
    incident = IncidentContext(
        cluster=cfg.cluster,
        window_start=cfg.window_start,
        window_end=cfg.window_end,
        symptom=cfg.symptom,
        svm=cfg.svm,
        volumes=volumes,
        asup_path=cfg.asup_path,
    )
    report = run_rca(
        incident,
        ems_data=ems_data,
        asup_summary=asup_summary,
        harvest_anomalies=harvest_anomalies,
    )

    _log(5, "Hypothesis generation — scoring candidates")
    for h in report["hypotheses"][:3]:
        _log(5, f"  → {h['id']}: {h['title']} (confidence={h['confidence']})")

    _log(6, "Validation & remediation plan")
    rc = report.get("root_cause")
    if rc:
        _log(6, f"  → Root cause: {rc['id']} — {rc['title']}")

    report["mode"] = "live" if cfg.live_ems else ("demo" if not cfg.use_live else "hybrid")
    report["volume_stats"] = vol_stats
    if cfg.use_live:
        report["ontap_host"] = os.environ.get("ONTAP_MGMT_HOST")
    return report


def main() -> None:
    import argparse

    from asup_agent.credentials import apply_credentials, resolve_credentials

    parser = argparse.ArgumentParser(
        description="Run ASUP RCA agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m asup_agent.agent              # prompts for cluster IP, username, password
  python3 -m asup_agent.agent --demo       # demo fixtures only, no prompts
  python3 -m asup_agent.agent --cluster-ip 192.168.1.50 --username admin
        """,
    )
    parser.add_argument("--demo", action="store_true", help="Run with demo fixtures (no ONTAP prompts)")
    parser.add_argument("--cluster-ip", help="ONTAP cluster management IP or hostname")
    parser.add_argument("--username", "-u", help="ONTAP REST API username")
    parser.add_argument("--password", "-p", help="ONTAP password (prefer prompt for security)")
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    parser.add_argument("--cluster", help="Cluster display name in report (default: cluster IP)")
    parser.add_argument("--window-start", default="2026-05-20T14:00:00Z")
    parser.add_argument("--window-end", default="2026-05-20T15:30:00Z")
    parser.add_argument("--symptom", default="NFS read latency spike on FlexGroup vol_fg01")
    parser.add_argument("--svm", default="svm_nfs01")
    parser.add_argument("--asup", help="Path to ASUP archive")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Deprecated: live mode is default unless --demo is set",
    )
    args = parser.parse_args()

    use_live = not args.demo
    cluster_name = args.cluster

    if use_live:
        creds = resolve_credentials(
            cluster_ip=args.cluster_ip,
            username=args.username,
            password=args.password,
            verify_ssl=False if args.no_verify_ssl else None,
            interactive=True,
            use_env=True,
        )
        if creds is None:
            print("ONTAP credentials required. Use --cluster-ip or set ONTAP_* env vars.", file=sys.stderr)
            sys.exit(1)
        apply_credentials(creds)
        if not cluster_name:
            cluster_name = creds.cluster_ip

    report = run_agent(AgentConfig(
        cluster=cluster_name or "demo-cluster-01",
        window_start=args.window_start,
        window_end=args.window_end,
        symptom=args.symptom,
        svm=args.svm,
        asup_path=args.asup,
        use_live=use_live,
    ))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
