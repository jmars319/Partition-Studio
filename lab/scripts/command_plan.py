#!/usr/bin/env python3
"""Build disposable-image command plans from planner-ready layouts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from discover_capabilities import discover_capabilities
from partitionlab_common import (
    DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
    LayoutError,
    find_partition,
    human_bytes,
    load_json,
    parse_size,
    partition_size_bytes,
    plan_operation,
    print_json,
    sector_size,
)


SCHEMA_COMMAND_PLAN = "partition-lab.command-plan.v1"


def _step(
    step: int,
    step_id: str,
    title: str,
    writes: bool,
    command: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step": step,
        "id": step_id,
        "title": title,
        "writes": writes,
        "command": command,
        "details": details or {},
    }


def geometry_steps(layout: dict[str, Any], increase_bytes: int, target_label: str, source_label: str) -> list[dict[str, Any]]:
    target = find_partition(layout, target_label)
    source = find_partition(layout, source_label)
    bytes_per_sector = sector_size(layout)
    increase_sectors = increase_bytes // bytes_per_sector
    source_size = partition_size_bytes(source, bytes_per_sector)
    target_size = partition_size_bytes(target, bytes_per_sector)

    return [
        _step(1, "snapshot-source-image", "copy source image to an isolated work image", False),
        _step(2, "validate-work-layout", "inspect the work image and confirm it matches the source plan", False),
        _step(
            3,
            "shrink-source-boundary",
            f"shrink {source_label} partition boundary by {human_bytes(increase_bytes)}",
            True,
            details={
                "partition": source_label,
                "new_start_sector": int(source["start_sector"]) + increase_sectors,
                "new_end_sector": int(source["end_sector"]),
                "new_size_bytes": source_size - increase_bytes,
            },
        ),
        _step(
            4,
            "move-source-bytes-right",
            f"move {source_label} raw bytes right by {human_bytes(increase_bytes)}",
            True,
            details={
                "partition": source_label,
                "from_start_sector": int(source["start_sector"]),
                "to_start_sector": int(source["start_sector"]) + increase_sectors,
                "bytes_to_copy": source_size - increase_bytes,
            },
        ),
        _step(
            5,
            "expand-target-boundary",
            f"expand {target_label} partition boundary by {human_bytes(increase_bytes)}",
            True,
            details={
                "partition": target_label,
                "new_start_sector": int(target["start_sector"]),
                "new_end_sector": int(target["end_sector"]) + increase_sectors,
                "new_size_bytes": target_size + increase_bytes,
            },
        ),
        _step(6, "rewrite-gpt", "rewrite primary and backup GPT entries on the work image", True),
        _step(7, "verify-result", "inspect and verify the mutated work image", False),
    ]


def real_ntfs_steps(layout: dict[str, Any], increase_bytes: int, target_label: str, source_label: str) -> list[dict[str, Any]]:
    target = find_partition(layout, target_label)
    source = find_partition(layout, source_label)
    bytes_per_sector = sector_size(layout)
    increase_sectors = increase_bytes // bytes_per_sector
    source_new_start = int(source["start_sector"]) + increase_sectors
    target_new_end = int(target["end_sector"]) + increase_sectors
    source_new_size = partition_size_bytes(source, bytes_per_sector) - increase_bytes

    return [
        _step(1, "attach-loop-readonly", "attach disposable image read-only for preflight", False, ["losetup", "--read-only", "--partscan", "<work-image>"]),
        _step(2, "ntfsresize-info-source", f"inspect {source_label} NTFS minimum size", False, ["ntfsresize", "--info", f"<{source_label}-partition-device>"]),
        _step(3, "ntfsresize-shrink-source", f"shrink {source_label} NTFS filesystem", True, ["ntfsresize", "--size", str(source_new_size), f"<{source_label}-partition-device>"]),
        _step(4, "parted-shrink-source", f"shrink {source_label} partition boundary", True, ["parted", "-s", "<work-image>", "unit", "s", "resizepart", str(source["number"]), str(source["end_sector"])]),
        _step(5, "move-source", f"move {source_label} right", True, ["<lab-move-engine>", str(source["start_sector"]), str(source_new_start)]),
        _step(6, "parted-expand-target", f"expand {target_label} partition boundary", True, ["parted", "-s", "<work-image>", "unit", "s", "resizepart", str(target["number"]), str(target_new_end)]),
        _step(7, "ntfsresize-grow-target", f"grow {target_label} NTFS filesystem", True, ["ntfsresize", "--force", f"<{target_label}-partition-device>"]),
        _step(8, "verify-native", "re-read layout and verify filesystems", False, ["parted", "-m", "-s", "<work-image>", "unit", "s", "print", "free"]),
    ]


def build_command_plan(
    layout: dict[str, Any],
    increase_bytes: int,
    target_label: str = "C",
    source_label: str = "E",
    min_source_free_after_bytes: int = DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
) -> dict[str, Any]:
    capabilities = discover_capabilities()
    planner = plan_operation(layout, increase_bytes, target_label, source_label, min_source_free_after_bytes)
    planner_ready = planner["plan_status"] == "ready"
    geometry_blockers = [] if planner_ready else [blocker["id"] for blocker in planner["blockers"]]
    real_ntfs_blockers = list(geometry_blockers)
    real_ntfs_blockers.extend(capabilities["modes"]["real_ntfs"]["blockers"])

    image = layout.get("image", {})
    if layout.get("mode") != "raw-geometry":
        geometry_blockers.append("layout-mode-not-raw-geometry")
    if not isinstance(image, dict) or not image.get("path"):
        geometry_blockers.append("layout-image-path-missing")

    return {
        "schema": SCHEMA_COMMAND_PLAN,
        "scenario": layout.get("scenario"),
        "input": {
            "target_label": target_label,
            "source_label": source_label,
            "increase_bytes": increase_bytes,
            "increase_human": human_bytes(increase_bytes),
            "minimum_source_free_after_bytes": min_source_free_after_bytes,
        },
        "planner": {
            "status": planner["plan_status"],
            "blockers": planner["blockers"],
            "warnings": planner["warnings"],
        },
        "source_image": image,
        "capabilities": {
            "schema": capabilities["schema"],
            "modes": capabilities["modes"],
            "blockers": capabilities["blockers"],
            "warnings": capabilities["warnings"],
        },
        "modes": {
            "raw_geometry": {
                "status": "ready" if not geometry_blockers else "blocked",
                "writes": True,
                "blockers": geometry_blockers,
                "steps": geometry_steps(layout, increase_bytes, target_label, source_label) if not geometry_blockers else [],
            },
            "real_ntfs": {
                "status": "ready" if not real_ntfs_blockers else "blocked",
                "dry_run_only": True,
                "writes": True,
                "blockers": real_ntfs_blockers,
                "steps": real_ntfs_steps(layout, increase_bytes, target_label, source_label) if planner_ready else [],
            },
        },
    }


def workflow_min_free(layout: dict[str, Any]) -> int:
    workflow = layout.get("workflow")
    if isinstance(workflow, dict) and isinstance(workflow.get("minimum_source_free_after_bytes"), int):
        return workflow["minimum_source_free_after_bytes"]
    return DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate disposable-image command plans. This script does not mutate images.")
    parser.add_argument("--layout", required=True, help="Normalized partition-lab.layout.v1 JSON.")
    parser.add_argument("--increase-c", default="40G", help="Amount to add to C. Default: 40G.")
    parser.add_argument("--target", default="C", help="Target partition label. Default: C.")
    parser.add_argument("--source", default="E", help="Source partition label. Default: E.")
    parser.add_argument("--min-source-free-after", help="Minimum free bytes that must remain on source.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        layout = load_json(args.layout)
        increase = parse_size(args.increase_c)
        min_free = parse_size(args.min_source_free_after) if args.min_source_free_after else workflow_min_free(layout)
        plan = build_command_plan(layout, increase, args.target, args.source, min_free)
    except (OSError, ValueError, LayoutError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(plan)
    else:
        print(f"Scenario: {plan.get('scenario')}")
        for name, mode in plan["modes"].items():
            print(f"{name}: {mode['status']}")
            if mode["blockers"]:
                print(f"  blockers: {', '.join(mode['blockers'])}")
            for step in mode["steps"]:
                write_marker = "writes" if step["writes"] else "read-only"
                print(f"  {step['step']}. {step['title']} [{write_marker}]")

    return 0 if plan["modes"]["raw_geometry"]["status"] == "ready" else 2


if __name__ == "__main__":
    sys.exit(main())
