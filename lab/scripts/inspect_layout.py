#!/usr/bin/env python3
"""Inspect a tenra Partition Lab layout JSON fixture."""

from __future__ import annotations

import argparse
import sys

from partitionlab_common import (
    human_bytes,
    load_json,
    normalized_partition,
    partitions,
    print_json,
    sector_size,
    validate_layout,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print a human or JSON summary of a tenra Partition Lab layout fixture.")
    parser.add_argument("layout", help="Layout JSON path.")
    parser.add_argument("--json", action="store_true", help="Emit normalized machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        layout = load_json(args.layout)
        sector_bytes = sector_size(layout)
        issues = validate_layout(layout)
        normalized = {
            "schema": "partition-lab.layout-inspection.v1",
            "scenario": layout.get("scenario"),
            "mode": layout.get("mode"),
            "disk": dict(layout["disk"]),
            "issues": issues,
        }
        normalized["disk"]["partitions"] = [normalized_partition(partition, sector_bytes) for partition in partitions(layout)]
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(normalized)
    else:
        disk = normalized["disk"]
        print(f"Scenario: {normalized.get('scenario')}")
        print(f"Mode: {normalized.get('mode')}")
        print(f"Disk: {disk.get('label')} {human_bytes(disk.get('size_bytes'))}, sector size {disk.get('sector_size')}")
        print("Partitions:")
        for partition in normalized["disk"]["partitions"]:
            print(
                "  "
                f"{partition.get('number')}: {partition.get('label')} "
                f"{partition.get('filesystem')} "
                f"start={partition.get('start_sector')} end={partition.get('end_sector')} "
                f"size={human_bytes(partition.get('size_bytes'))} "
                f"used={human_bytes(partition.get('used_bytes'))} free={human_bytes(partition.get('free_bytes'))}"
            )
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue['severity']}: {issue['message']}")

    return 0 if not [issue for issue in normalized["issues"] if issue["severity"] == "error"] else 2


if __name__ == "__main__":
    sys.exit(main())
