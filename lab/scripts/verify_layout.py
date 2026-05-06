#!/usr/bin/env python3
"""Verify expected C/E geometry and mock filesystem invariants."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from partitionlab_common import (
    DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
    LayoutError,
    alignment_sectors,
    are_adjacent,
    find_partition,
    human_bytes,
    load_json,
    parse_size,
    partition_size_bytes,
    plan_operation,
    print_json,
    sector_size,
    simulated_after_layout,
)


def check(name: str, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "status": "pass" if passed else "fail", "details": details or {}}


def compare_layouts(
    before: dict[str, Any],
    after: dict[str, Any],
    increase_bytes: int,
    target_label: str,
    source_label: str,
    min_source_free_after_bytes: int,
) -> dict[str, Any]:
    before_sector_size = sector_size(before)
    after_sector_size = sector_size(after)
    if before_sector_size != after_sector_size:
        raise LayoutError("before and after sector sizes differ")

    target_before = find_partition(before, target_label)
    source_before = find_partition(before, source_label)
    target_after = find_partition(after, target_label)
    source_after = find_partition(after, source_label)

    target_before_size = partition_size_bytes(target_before, before_sector_size)
    source_before_size = partition_size_bytes(source_before, before_sector_size)
    target_after_size = partition_size_bytes(target_after, after_sector_size)
    source_after_size = partition_size_bytes(source_after, after_sector_size)

    alignment = alignment_sectors(after)
    before_source_files = set(source_before.get("files") or [])
    after_source_files = set(source_after.get("files") or [])
    after_source_free = source_after.get("free_bytes")

    checks = [
        check(
            f"{target_label} grew by expected amount",
            target_after_size - target_before_size == increase_bytes,
            {
                "before_size": target_before_size,
                "after_size": target_after_size,
                "expected_delta": increase_bytes,
                "actual_delta": target_after_size - target_before_size,
            },
        ),
        check(
            f"{source_label} shrank by expected amount",
            source_before_size - source_after_size == increase_bytes,
            {
                "before_size": source_before_size,
                "after_size": source_after_size,
                "expected_delta": increase_bytes,
                "actual_delta": source_before_size - source_after_size,
            },
        ),
        check(
            "partitions are aligned",
            int(target_after["start_sector"]) % alignment == 0 and int(source_after["start_sector"]) % alignment == 0,
            {"alignment_sectors": alignment},
        ),
        check(
            f"{target_label} is adjacent to {source_label} after expansion",
            are_adjacent(target_after, source_after),
            {
                "target_end_sector": target_after["end_sector"],
                "source_start_sector": source_after["start_sector"],
            },
        ),
        check(
            f"files on {source_label} still exist",
            bool(before_source_files) and before_source_files.issubset(after_source_files),
            {
                "before_file_count": len(before_source_files),
                "after_file_count": len(after_source_files),
                "missing": sorted(before_source_files - after_source_files),
            },
        ),
        check(
            "filesystems are recognizable",
            str(target_after.get("filesystem", "")).lower() == "ntfs"
            and str(source_after.get("filesystem", "")).lower() == "ntfs",
            {
                "target_filesystem": target_after.get("filesystem"),
                "source_filesystem": source_after.get("filesystem"),
            },
        ),
        check(
            f"{source_label} retains required free space",
            isinstance(after_source_free, int) and after_source_free >= min_source_free_after_bytes,
            {
                "source_free_bytes": after_source_free,
                "minimum_source_free_after_bytes": min_source_free_after_bytes,
            },
        ),
    ]

    passed = all(item["status"] == "pass" for item in checks)
    return {
        "schema": "partition-lab.verify.v1",
        "scenario": before.get("scenario"),
        "verification_status": "pass" if passed else "fail",
        "mode": "mock" if after.get("mode") == "mock" else "layout",
        "input": {
            "target_label": target_label,
            "source_label": source_label,
            "increase_bytes": increase_bytes,
        },
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify mock or inspected layouts against the tenra Partition Lab target workflow.")
    parser.add_argument("--before", required=True, help="Before layout JSON.")
    parser.add_argument("--after", help="After layout JSON. If omitted, a mock after-layout is simulated from --before.")
    parser.add_argument("--increase-c", default="40G", help="Expected amount added to C. Default: 40G.")
    parser.add_argument("--target", default="C", help="Target partition label. Default: C.")
    parser.add_argument("--source", default="E", help="Source partition label. Default: E.")
    parser.add_argument(
        "--min-source-free-after",
        default=str(DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES),
        help="Minimum free bytes that must remain on the source partition. Default: 1GiB.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        before = load_json(args.before)
        increase = parse_size(args.increase_c)
        min_free = parse_size(args.min_source_free_after)
        plan = plan_operation(before, increase, args.target, args.source, min_free)
        if plan["plan_status"] != "ready":
            result = {
                "schema": "partition-lab.verify.v1",
                "scenario": before.get("scenario"),
                "verification_status": "fail",
                "mode": "mock",
                "input": {
                    "target_label": args.target,
                    "source_label": args.source,
                    "increase_bytes": increase,
                },
                "checks": [
                    check(
                        "planner is ready",
                        False,
                        {"blockers": plan["blockers"]},
                    )
                ],
            }
        else:
            after = load_json(args.after) if args.after else simulated_after_layout(before, increase, args.target, args.source)
            result = compare_layouts(before, after, increase, args.target, args.source, min_free)
    except (OSError, ValueError, LayoutError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(result)
    else:
        print(f"Scenario: {result.get('scenario')}")
        print(f"Verification status: {result['verification_status']}")
        for item in result["checks"]:
            print(f"  {item['status'].upper()}: {item['name']}")
            if item["status"] != "pass":
                print(f"    details: {item['details']}")
        print(f"Expected increase: {human_bytes(result['input']['increase_bytes'])}")

    return 0 if result["verification_status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
