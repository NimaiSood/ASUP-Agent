"""Cross-source timeline correlation for RCA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TimelineEvent:
    timestamp: str
    source: str
    category: str
    summary: str
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_ts(value: str) -> datetime | None:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
    return None


def build_timeline(
    *,
    ems_records: list[dict[str, Any]] | None = None,
    syslog_events: list[dict[str, str]] | None = None,
    harvest_anomalies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge EMS, syslog, and Harvest anomaly points into a sorted timeline."""
    events: list[TimelineEvent] = []

    for rec in ems_records or []:
        ts = rec.get("time", "")
        msg = rec.get("log_message", rec.get("message", {}).get("name", ""))
        events.append(TimelineEvent(
            timestamp=ts,
            source="ems",
            category=rec.get("message", {}).get("name", "unknown"),
            summary=str(msg)[:200],
            raw=rec,
        ))

    for ev in syslog_events or []:
        events.append(TimelineEvent(
            timestamp="",
            source="asup_syslog",
            category=ev.get("category", "unknown"),
            summary=ev.get("line", "")[:200],
            raw=ev,
        ))

    for anom in harvest_anomalies or []:
        events.append(TimelineEvent(
            timestamp=anom.get("timestamp", ""),
            source="harvest",
            category=anom.get("metric", "metric_anomaly"),
            summary=anom.get("description", ""),
            raw=anom,
        ))

    def sort_key(e: TimelineEvent) -> tuple[int, str]:
        parsed = _parse_ts(e.timestamp)
        return (0, parsed.isoformat()) if parsed else (1, e.timestamp)

    events.sort(key=sort_key)
    return [
        {
            "timestamp": e.timestamp,
            "source": e.source,
            "category": e.category,
            "summary": e.summary,
        }
        for e in events
    ]
