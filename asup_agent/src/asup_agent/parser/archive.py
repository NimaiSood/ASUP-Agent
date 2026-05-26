"""AutoSupport archive extraction and artifact discovery."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

TARGET_FILES = {
    "syslog": ["syslog", "messages", "syslog.*"],
    "wafl.log": ["wafl.log", "wafl_*"],
    "statit": ["statit", "statit_*", "statit.out"],
    "nblade": ["nblade", "nblade_*"],
    "large_io": ["large_io", "largeio", "lio_*"],
}


def _extract_7z(archive: Path, dest: Path) -> None:
    try:
        import py7zr
    except ImportError as err:
        raise ImportError("Install py7zr: pip install 'asup-agent[archive]'") from err

    decrypt_key = os.environ.get("ASUP_DECRYPT_KEY")
    key_file = archive.with_suffix(".key")
    if not decrypt_key and key_file.exists():
        decrypt_key = key_file.read_text().strip()

    with py7zr.SevenZipFile(archive, mode="r", password=decrypt_key) as zf:
        zf.extractall(path=dest)


def _extract_tar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:*") as tf:
        tf.extractall(dest)


def _extract(archive: Path, dest: Path) -> None:
    suffix = archive.suffix.lower()
    name = archive.name.lower()
    if suffix == ".7z" or name.endswith(".7z"):
        _extract_7z(archive, dest)
    elif suffix in (".gz", ".tgz", ".bz2", ".xz") or ".tar" in name:
        _extract_tar(archive, dest)
    elif archive.is_dir():
        shutil.copytree(archive, dest, dirs_exist_ok=True)
    else:
        raise ValueError(f"Unsupported archive format: {archive}")


def _find_artifacts(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {k: [] for k in TARGET_FILES}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        for category, patterns in TARGET_FILES.items():
            if any(p.replace("*", "") in name for p in patterns):
                found[category].append(str(path))
    return found


def parse_archive(archive_path: str, output_dir: str | None = None) -> dict[str, Any]:
    """Extract ASUP archive and locate diagnostic artifacts."""
    archive = Path(archive_path).expanduser().resolve()
    if output_dir:
        dest = Path(output_dir).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest = Path(tempfile.mkdtemp(prefix="asup_"))

    if archive.is_dir():
        work_root = archive
    else:
        _extract(archive, dest)
        work_root = dest

    artifacts = _find_artifacts(work_root)
    summary = {
        "archive": str(archive),
        "extract_root": str(work_root),
        "artifacts": artifacts,
        "artifact_counts": {k: len(v) for k, v in artifacts.items()},
    }

    # Run lightweight parsers on discovered files
    from asup_agent.parser.syslog import parse_syslog_files
    from asup_agent.parser.wafl import parse_wafl_files
    from asup_agent.parser.statit import parse_statit_files

    if artifacts["syslog"]:
        summary["syslog_events"] = parse_syslog_files(artifacts["syslog"])
    if artifacts["wafl.log"]:
        summary["wafl_signals"] = parse_wafl_files(artifacts["wafl.log"])
    if artifacts["statit"] or artifacts["nblade"] or artifacts["large_io"]:
        statit_paths = artifacts["statit"] + artifacts["nblade"] + artifacts["large_io"]
        summary["statit_signals"] = parse_statit_files(statit_paths)

    return summary
