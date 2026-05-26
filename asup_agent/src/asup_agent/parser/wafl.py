"""wafl.log signal extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

WAFL_SIGNALS = [
    (re.compile(r"alloc.*delay|allocation.*slow", re.I), "wafl_alloc_delay"),
    (re.compile(r"consistency.*point|cp.*delay", re.I), "cp_delay"),
    (re.compile(r"fragment|realloc", re.I), "fragmentation"),
    (re.compile(r"inode.*busy|metadata.*wait", re.I), "metadata_contention"),
    (re.compile(r"large.?io|lio", re.I), "large_io_wafl"),
]


def parse_wafl_files(paths: list[str], max_lines: int = 5000) -> dict[str, Any]:
    signals: dict[str, int] = {name: 0 for _, name in WAFL_SIGNALS}
    samples: list[dict[str, str]] = []

    for path_str in paths:
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-max_lines:]:
            for pattern, name in WAFL_SIGNALS:
                if pattern.search(line):
                    signals[name] += 1
                    if len(samples) < 50:
                        samples.append({"signal": name, "line": line[:500]})
                    break

    return {"signals": signals, "samples": samples}
