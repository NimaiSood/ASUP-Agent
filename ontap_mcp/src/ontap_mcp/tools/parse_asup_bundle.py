"""Fast selective ASUP bundle parser — in-memory extract + structured summaries."""

from __future__ import annotations

import logging
import os
import re
import tarfile
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterator

from ontap_mcp.tool_schemas import ParseAsupBundleInput, VALID_SUBSYSTEMS

logger = logging.getLogger(__name__)

SUBSYSTEM_GLOBS: dict[str, list[str]] = {
    "syslog": ["*syslog*", "*messages*", "*/syslog/*"],
    "wafl.log": ["*wafl.log*", "*wafl_*"],
    "statit": ["*statit*", "*statit.out*"],
    "nblade": ["*nblade*", "*nblade_*"],
    "large_io": ["*large_io*", "*largeio*", "*lio_*"],
}

ISO_TS = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
SYSLOG_TS = re.compile(
    r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})|^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _line_timestamp(line: str) -> datetime | None:
    m = ISO_TS.search(line)
    if m:
        return _parse_iso(m.group(1).replace(" ", "T"))
    return None


def _in_time_window(
    line: str,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if start is None and end is None:
        return True
    ts = _line_timestamp(line)
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if start and ts < start:
        return False
    if end and ts > end:
        return False
    return True


def _matches_subsystem(name: str, subsystem: str) -> bool:
    lowered = name.lower().replace("\\", "/")
    for pattern in SUBSYSTEM_GLOBS.get(subsystem, []):
        if fnmatch(lowered, pattern.lower()):
            return True
    return False


def _iter_tar_members(archive: Path, subsystems: set[str]) -> Iterator[tuple[str, bytes]]:
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if not any(_matches_subsystem(member.name, sub) for sub in subsystems):
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            yield member.name, data
            logger.debug("Extracted tar member %s (%d bytes)", member.name, len(data))


def _iter_7z_members(archive: Path, subsystems: set[str]) -> Iterator[tuple[str, bytes]]:
    try:
        import py7zr
    except ImportError as err:
        raise ImportError("Install py7zr: pip install py7zr") from err

    decrypt_key = os.environ.get("ASUP_DECRYPT_KEY")
    key_file = archive.with_suffix(".key")
    if not decrypt_key and key_file.exists():
        decrypt_key = key_file.read_text().strip()

    targets = set()
    for sub in subsystems:
        targets.update(SUBSYSTEM_GLOBS.get(sub, []))

    with py7zr.SevenZipFile(archive, mode="r", password=decrypt_key) as zf:
        all_names = zf.getnames()
        selected = [
            n for n in all_names
            if any(_matches_subsystem(n, sub) for sub in subsystems)
        ]
        if not selected:
            return
        extracted = zf.read(selected)
        for name, bio in extracted.items():
            if isinstance(bio, (bytes, bytearray)):
                payload = bytes(bio)
            else:
                payload = bio.read()
            yield name, payload
            logger.debug("Extracted 7z member %s (%d bytes)", name, len(payload))


def _extract_members(archive: Path, subsystems: set[str]) -> dict[str, bytes]:
    suffix = archive.suffix.lower()
    name = archive.name.lower()
    members: dict[str, bytes] = {}

    if suffix == ".7z" or name.endswith(".7z"):
        source = _iter_7z_members(archive, subsystems)
    elif suffix in (".gz", ".tgz", ".bz2", ".xz") or ".tar" in name:
        source = _iter_tar_members(archive, subsystems)
    elif archive.is_dir():
        for path in archive.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(archive))
            if any(_matches_subsystem(rel, sub) for sub in subsystems):
                members[rel] = path.read_bytes()
        return members
    else:
        raise ValueError(f"Unsupported archive format: {archive}")

    for member_name, payload in source:
        members[member_name] = payload
    return members


def _summarize_syslog(
    members: dict[str, bytes],
    *,
    start: datetime | None,
    end: datetime | None,
    max_events: int,
) -> dict[str, Any]:
    try:
        from asup_agent.parser.syslog import RCA_PATTERNS
    except ImportError:
        RCA_PATTERNS = []

    category_counts: dict[str, int] = {}
    samples: list[dict[str, str]] = []

    for name, payload in members.items():
        if "syslog" not in name.lower() and "messages" not in name.lower():
            continue
        text = payload.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if not _in_time_window(line, start, end):
                continue
            matched = False
            for pattern, category in RCA_PATTERNS:
                if pattern.search(line):
                    category_counts[category] = category_counts.get(category, 0) + 1
                    if len(samples) < max_events:
                        samples.append({"category": category, "source": name, "line": line[:400]})
                    matched = True
                    break
            if not matched and len(samples) < max_events and SYSLOG_TS.match(line):
                samples.append({"category": "other", "source": name, "line": line[:400]})

    return {"category_counts": category_counts, "sample_events": samples[:max_events]}


def _summarize_wafl(
    members: dict[str, bytes],
    *,
    start: datetime | None,
    end: datetime | None,
    max_events: int,
) -> dict[str, Any]:
    try:
        from asup_agent.parser.wafl import WAFL_SIGNALS
    except ImportError:
        WAFL_SIGNALS = []

    signals: dict[str, int] = {}
    samples: list[dict[str, str]] = []

    for name, payload in members.items():
        if "wafl" not in name.lower():
            continue
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not _in_time_window(line, start, end):
                continue
            for pattern, signal in WAFL_SIGNALS:
                if pattern.search(line):
                    signals[signal] = signals.get(signal, 0) + 1
                    if len(samples) < max_events:
                        samples.append({"signal": signal, "source": name, "line": line[:400]})
                    break

    return {"signals": signals, "samples": samples[:max_events]}


def _summarize_statit(
    members: dict[str, bytes],
    *,
    start: datetime | None,
    end: datetime | None,
    max_events: int,
) -> dict[str, Any]:
    try:
        from asup_agent.parser.statit import STATIT_SECTIONS
    except ImportError:
        STATIT_SECTIONS = {}

    section_hits: dict[str, int] = {}
    latency_samples: list[dict[str, str]] = []
    latency_re = re.compile(r"latency[=:\s]+(\d+(?:\.\d+)?)\s*(us|ms|µs)?", re.I)

    statit_keys = ("statit", "nblade", "large_io")
    for name, payload in members.items():
        lowered = name.lower()
        if not any(k in lowered for k in statit_keys):
            continue
        text = payload.decode("utf-8", errors="replace")
        for section, pattern in STATIT_SECTIONS.items():
            if pattern.search(text):
                section_hits[section] = section_hits.get(section, 0) + 1
        for line in text.splitlines():
            if not _in_time_window(line, start, end):
                continue
            m = latency_re.search(line)
            if m and len(latency_samples) < max_events:
                latency_samples.append({
                    "value": m.group(1),
                    "unit": m.group(2) or "unknown",
                    "source": name,
                    "line": line[:300],
                })

    return {
        "section_hits": section_hits,
        "latency_samples": latency_samples[:max_events],
        "files_parsed": len(members),
    }


def parse_asup_bundle(params: ParseAsupBundleInput) -> dict[str, Any]:
    """Extract requested subsystems from ASUP archive and return JSON summaries."""
    archive = Path(params.archive_path).expanduser().resolve()
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")

    subsystems = set(params.target_subsystems)
    start = _parse_iso(params.time_start)
    end = _parse_iso(params.time_end)

    logger.info(
        "Parsing ASUP %s subsystems=%s window=%s..%s",
        archive,
        sorted(subsystems),
        params.time_start,
        params.time_end,
    )

    members = _extract_members(archive, subsystems)
    by_subsystem: dict[str, list[str]] = {s: [] for s in VALID_SUBSYSTEMS}
    for name in members:
        for sub in subsystems:
            if _matches_subsystem(name, sub):
                by_subsystem[sub].append(name)

    summaries: dict[str, Any] = {}
    max_ev = params.max_summary_events

    if "syslog" in subsystems:
        syslog_members = {k: v for k, v in members.items() if _matches_subsystem(k, "syslog")}
        summaries["syslog"] = _summarize_syslog(syslog_members, start=start, end=end, max_events=max_ev)

    if "wafl.log" in subsystems:
        wafl_members = {k: v for k, v in members.items() if _matches_subsystem(k, "wafl.log")}
        summaries["wafl.log"] = _summarize_wafl(wafl_members, start=start, end=end, max_events=max_ev)

    statit_related = subsystems & {"statit", "nblade", "large_io"}
    if statit_related:
        statit_members = {
            k: v for k, v in members.items()
            if any(_matches_subsystem(k, s) for s in statit_related)
        }
        summaries["statit"] = _summarize_statit(statit_members, start=start, end=end, max_events=max_ev)

    result = {
        "archive": str(archive),
        "target_subsystems": params.target_subsystems,
        "time_window": {"start": params.time_start, "end": params.time_end},
        "artifacts_found": {k: v for k, v in by_subsystem.items() if v},
        "artifact_counts": {k: len(v) for k, v in by_subsystem.items() if v},
        "bytes_extracted": sum(len(v) for v in members.values()),
        "summaries": summaries,
    }
    logger.info(
        "ASUP parse complete: %d files, %d bytes",
        len(members),
        result["bytes_extracted"],
    )
    return result
