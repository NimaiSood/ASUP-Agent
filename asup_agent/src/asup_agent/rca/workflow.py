"""RCA workflow orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from asup_agent.rca.correlator import build_timeline
from asup_agent.rca.hypotheses import score_hypotheses


@dataclass
class IncidentContext:
    cluster: str
    window_start: str
    window_end: str
    symptom: str
    svm: str | None = None
    volumes: list[str] = field(default_factory=list)
    asup_path: str | None = None


REMEDIATION_MAP = {
    "H1": [
        "Reduce concurrent stat-heavy workloads (find, du, ls -R) on FlexGroup constituents",
        "Spread metadata-heavy workloads across SVMs or schedule off-peak",
        "Evaluate FlexGroup constituent count vs. metadata load",
    ],
    "H2": [
        "Review read cache policy and workload IO size distribution",
        "Check for sequential large-read patterns thrashing cache",
        "Inspect aggregate free space and WAFL fragmentation (reallocate if needed)",
    ],
    "H3": [
        "Validate client network path and MTU/end-to-end connectivity",
        "Compare nblade vs. dblade latency split in statit",
        "Check for CS session limits or connection storms",
    ],
    "H4": [
        "Identify disk busy hotspots via Harvest disk_busy metrics",
        "Check for RAID rebuild or degraded aggregate",
        "Consider aggregate expansion or workload rebalance",
    ],
    "H5": [
        "Inspect cluster interconnect utilization during stat storm window",
        "Verify node count and upgrade cluster network if sustained saturation",
        "Review FlexGroup cross-node metadata placement",
    ],
}


def run_rca(
    incident: IncidentContext,
    *,
    ems_data: dict[str, Any] | None = None,
    asup_summary: dict[str, Any] | None = None,
    harvest_anomalies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute RCA correlation and hypothesis ranking from gathered evidence."""
    ems_records = (ems_data or {}).get("records", [])
    syslog_events = (asup_summary or {}).get("syslog_events", {}).get("sample_events", [])
    wafl_signals = (asup_summary or {}).get("wafl_signals", {}).get("signals", {})
    statit_signals = (asup_summary or {}).get("statit_signals", {})

    ems_category_counts: dict[str, int] = {}
    for rec in ems_records:
        name = rec.get("message", {}).get("name", "").lower()
        if "stat" in name or "flexgroup" in name:
            ems_category_counts["stat"] = ems_category_counts.get("stat", 0) + 1
        if "nblade" in name or "cs." in name:
            ems_category_counts["nblade"] = ems_category_counts.get("nblade", 0) + 1
        if "large_io" in name or "largeio" in name:
            ems_category_counts["large_io"] = ems_category_counts.get("large_io", 0) + 1
        if "wafl" in name:
            ems_category_counts["wafl"] = ems_category_counts.get("wafl", 0) + 1
        if "resource" in name or "cpu" in name:
            ems_category_counts["resource"] = ems_category_counts.get("resource", 0) + 1

    timeline = build_timeline(
        ems_records=ems_records,
        syslog_events=syslog_events,
        harvest_anomalies=harvest_anomalies,
    )

    syslog_counts = (asup_summary or {}).get("syslog_events", {}).get("category_counts", {})
    hypotheses = score_hypotheses(
        ems_category_counts=ems_category_counts,
        syslog_category_counts=syslog_counts,
        wafl_signals=wafl_signals,
        statit_section_hits=statit_signals.get("section_hits", {}),
    )

    root_cause = hypotheses[0] if hypotheses else None
    remediation = REMEDIATION_MAP.get(root_cause["id"], []) if root_cause else []

    return {
        "incident": {
            "cluster": incident.cluster,
            "window": f"{incident.window_start} — {incident.window_end}",
            "symptom": incident.symptom,
            "svm": incident.svm,
            "volumes": incident.volumes,
        },
        "timeline": timeline,
        "hypotheses": hypotheses,
        "root_cause": root_cause,
        "remediation_plan": remediation,
        "evidence_summary": {
            "ems_events": len(ems_records),
            "syslog_samples": len(syslog_events),
            "wafl_signals": wafl_signals,
            "statit_sections": statit_signals.get("section_hits", {}),
        },
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run ONTAP RCA from JSON evidence files")
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--symptom", required=True)
    parser.add_argument("--ems-json", help="Path to EMS JSON export")
    parser.add_argument("--asup-json", help="Path to parsed ASUP summary JSON")
    args = parser.parse_args()

    ems_data = json.loads(open(args.ems_json).read()) if args.ems_json else None
    asup_summary = json.loads(open(args.asup_json).read()) if args.asup_json else None

    report = run_rca(
        IncidentContext(
            cluster=args.cluster,
            window_start=args.window_start,
            window_end=args.window_end,
            symptom=args.symptom,
        ),
        ems_data=ems_data,
        asup_summary=asup_summary,
    )
    print(json.dumps(report, indent=2))
