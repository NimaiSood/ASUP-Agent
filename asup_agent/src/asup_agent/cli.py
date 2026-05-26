"""CLI for ASUP archive parsing."""

from __future__ import annotations

import argparse
import json
import sys

from asup_agent.parser.archive import parse_archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse NetApp AutoSupport archive")
    parser.add_argument("archive", help="Path to ASUP .7z, .tar.gz, or extracted directory")
    parser.add_argument("--output", "-o", help="Extraction output directory")
    args = parser.parse_args()

    try:
        result = parse_archive(args.archive, output_dir=args.output)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
