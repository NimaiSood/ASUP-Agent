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
        ems_data = _load_fixture("ems_events.json")
        _log(2, f"  → {ems_data.get('num_records', 0)} EMS events (fixture)")
    else:
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

    report["mode"] = "live" if cfg.use_live and ems_data else "demo"
    report["volume_stats"] = vol_stats
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run ASUP RCA agent")
    parser.add_argument("--cluster", default="demo-cluster-01")
    parser.add_argument("--window-start", default="2026-05-20T14:00:00Z")
    parser.add_argument("--window-end", default="2026-05-20T15:30:00Z")
    parser.add_argument("--symptom", default="NFS read latency spike on FlexGroup vol_fg01")
    parser.add_argument("--svm", default="svm_nfs01")
    parser.add_argument("--asup", help="Path to ASUP archive")
    parser.add_argument("--live", action="store_true", help="Use live ONTAP REST (requires env vars)")
    args = parser.parse_args()

    report = run_agent(AgentConfig(
        cluster=args.cluster,
        window_start=args.window_start,
        window_end=args.window_end,
        symptom=args.symptom,
        svm=args.svm,
        asup_path=args.asup,
        use_live=args.live,
    ))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
