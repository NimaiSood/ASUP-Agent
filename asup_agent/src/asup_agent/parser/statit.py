"""statit output parsing for nblade and large IO diagnostics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

STATIT_SECTIONS = {
    "nblade": re.compile(r"nblade|network.*blade|protocol.*latency", re.I),
    "large_io": re.compile(r"large.?io|lio|bigio|>.*64k", re.I),
    "disk": re.compile(r"disk.*busy|disk.*latency|raid", re.I),
    "cpu": re.compile(r"cpu.*util|processor.*busy", re.I),
    "stat": re.compile(r"stat.*ops|metadata.*ops|getattr|lookup", re.I),
}


def parse_statit_files(paths: list[str], max_lines: int = 10000) -> dict[str, Any]:
    section_hits: dict[str, int] = {k: 0 for k in STATIT_SECTIONS}
    latency_samples: list[dict[str, str]] = []
    latency_re = re.compile(r"latency[=:\s]+(\d+(?:\.\d+)?)\s*(us|ms|µs)?", re.I)

    for path_str in paths:
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        for section, pattern in STATIT_SECTIONS.items():
            if pattern.search(content):
                section_hits[section] += content.lower().count(pattern.pattern.split("|")[0])

        for line in content.splitlines()[-max_lines:]:
            m = latency_re.search(line)
            if m and len(latency_samples) < 100:
                latency_samples.append({
                    "value": m.group(1),
                    "unit": m.group(2) or "unknown",
                    "line": line[:300],
                    "source": path.name,
                })

    return {
        "section_hits": section_hits,
        "latency_samples": latency_samples,
        "files_parsed": len(paths),
    }
