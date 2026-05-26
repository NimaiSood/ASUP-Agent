"""Root-cause hypothesis generation and ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Hypothesis:
    id: str
    title: str
    description: str
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        total = len(self.supporting) + len(self.contradicting)
        if total == 0:
            return 0.0
        return len(self.supporting) / total


HYPOTHESIS_CATALOG = [
    Hypothesis(
        id="H1",
        title="FlexGroup stat storm saturating Nblade CPU",
        description="High-concurrency metadata operations across constituents causing CPU starvation.",
    ),
    Hypothesis(
        id="H2",
        title="Large IO lifecycle bottleneck",
        description="Large sequential IO thrashing read cache or hitting WAFL allocation delays.",
    ),
    Hypothesis(
        id="H3",
        title="Nblade / CS layer network processing delay",
        description="Client-facing network blade or cluster session layer queuing requests.",
    ),
    Hypothesis(
        id="H4",
        title="Dblade backend disk serialization",
        description="Disk busy or RAID rebuild causing backend latency propagation.",
    ),
    Hypothesis(
        id="H5",
        title="FlexGroup interconnect contention",
        description="Cluster network saturation during cross-node metadata coordination.",
    ),
]


def score_hypotheses(
    *,
    ems_category_counts: dict[str, int] | None = None,
    syslog_category_counts: dict[str, int] | None = None,
    wafl_signals: dict[str, int] | None = None,
    statit_section_hits: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Score hypotheses against parsed evidence."""
    ems = ems_category_counts or {}
    syslog = syslog_category_counts or {}
    wafl = wafl_signals or {}
    statit = statit_section_hits or {}

    hypotheses = [Hypothesis(h.id, h.title, h.description) for h in HYPOTHESIS_CATALOG]

    stat_score = ems.get("stat", 0) + syslog.get("stat_storm", 0) + statit.get("stat", 0)
    if stat_score > 0:
        hypotheses[0].supporting.append(f"Stat/metadata signals: {stat_score}")
    if statit.get("cpu", 0) > 0:
        hypotheses[0].supporting.append(f"CPU utilization in statit: {statit['cpu']}")

    lio_score = syslog.get("large_io", 0) + wafl.get("large_io_wafl", 0) + statit.get("large_io", 0)
    if lio_score > 0:
        hypotheses[1].supporting.append(f"Large IO signals: {lio_score}")
    if wafl.get("wafl_alloc_delay", 0) > 0:
        hypotheses[1].supporting.append(f"WAFL allocation delays: {wafl['wafl_alloc_delay']}")

    nblade_score = syslog.get("nblade", 0) + statit.get("nblade", 0)
    if nblade_score > 0:
        hypotheses[2].supporting.append(f"Nblade signals: {nblade_score}")

    disk_score = statit.get("disk", 0)
    if disk_score > 0:
        hypotheses[3].supporting.append(f"Disk busy/latency in statit: {disk_score}")
    if wafl.get("cp_delay", 0) > 0:
        hypotheses[3].supporting.append(f"CP delays in wafl.log: {wafl['cp_delay']}")

    if stat_score > 0 and nblade_score > 0:
        hypotheses[4].supporting.append("Concurrent stat + nblade activity suggests interconnect load")

    ranked = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
    return [
        {
            "id": h.id,
            "title": h.title,
            "description": h.description,
            "confidence": round(h.confidence, 2),
            "supporting": h.supporting,
            "contradicting": h.contradicting,
        }
        for h in ranked
    ]
