"""Syslog parsing for RCA-relevant events."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

RCA_PATTERNS = [
    (re.compile(r"nblade|network.*latency|cs\.|cluster.session", re.I), "nblade"),
    (re.compile(r"wafl|consistency|alloc|inode", re.I), "wafl"),
    (re.compile(r"stat\.|stat storm|metadata", re.I), "stat_storm"),
    (re.compile(r"large.?io|lio|bigio", re.I), "large_io"),
    (re.compile(r"cpu.*starv|resource.*exhaust|queue.*depth", re.I), "resource"),
]


def parse_syslog_files(paths: list[str], max_lines: int = 2000) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    category_counts: dict[str, int] = {c: 0 for _, c in RCA_PATTERNS}

    for path_str in paths:
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-max_lines:]:
            for pattern, category in RCA_PATTERNS:
                if pattern.search(line):
                    category_counts[category] += 1
                    if len(events) < 500:
                        events.append({"category": category, "line": line[:500], "source": str(path)})
                    break

    return {
        "event_count": len(events),
        "category_counts": category_counts,
        "sample_events": events[:100],
    }
