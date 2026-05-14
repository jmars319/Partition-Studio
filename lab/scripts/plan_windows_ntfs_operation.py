#!/usr/bin/env python3
"""Emit a Windows NTFS operation dry-run plan without mutating disks."""

from __future__ import annotations

import argparse
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from partitionlab_common import parse_size, print_json, safety_assessment


SCHEMA_WINDOWS_NTFS_PLAN = "partition-lab.windows-ntfs-plan.v1"


def blocker(blocker_id: str, message: str) -> dict[str, str]:
    return {"id": blocker_id, "message": message}


def build_windows_ntfs_plan(image: Path, increase_c: str, target: str = "C", source: str = "E") -> dict[str, Any]:
    increase_bytes = parse_size(increase_c)
    safety = safety_assessment(image)
    blockers: list[dict[str, str]] = [
        blocker("real-ntfs-mutation-not-implemented", "real NTFS shrink/grow/move execution is not implemented")
    ]
    if not safety["under_test_images"]:
        blockers.append(blocker("image-outside-test-images", "Windows NTFS planning is limited to lab/test-images"))
    if safety["windows_physical_drive"] or safety["denylisted_system_device"] or safety["block_device"]:
        blockers.append(blocker("physical-disk-refused", "physical and system disks are refused"))

    return {
        "schema": SCHEMA_WINDOWS_NTFS_PLAN,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "dry-run-only" if len(blockers) == 1 else "refused",
        "host": {
            "platform": platform.system(),
            "machine": platform.machine(),
            "windows_required": True,
        },
        "input": {
            "image": str(image),
            "target_label": target,
            "source_label": source,
            "increase_c": increase_c,
            "increase_bytes": increase_bytes,
        },
        "safety": safety,
        "blockers": blockers,
        "preconditions": [
            {"id": "administrator-powershell", "required": True, "description": "Run from Administrator PowerShell on Windows."},
            {"id": "disposable-vhdx-only", "required": True, "description": "Use a disposable VHDX under lab/test-images."},
            {"id": "bitlocker-off", "required": True, "description": "Refuse encrypted or BitLocker-protected volumes."},
            {"id": "filesystem-clean", "required": True, "description": "Refuse dirty, repair-pending, or mounted production filesystems."},
            {"id": "physical-disk-refusal", "required": True, "description": "Refuse PhysicalDrive paths and system disks."},
        ],
        "dry_run_steps": [
            {"step": 1, "id": "attach-vhdx-readonly", "writes": False, "command": ["Mount-DiskImage", "-ImagePath", "<vhdx>", "-Access", "ReadOnly"]},
            {"step": 2, "id": "inspect-volumes", "writes": False, "command": ["Get-Disk", "|", "Get-Partition", "|", "Get-Volume"]},
            {"step": 3, "id": "check-bitlocker", "writes": False, "command": ["Get-BitLockerVolume", "-MountPoint", "<source,target>"]},
            {"step": 4, "id": "check-filesystem-state", "writes": False, "command": ["Repair-Volume", "-Scan", "-DriveLetter", "<source,target>"]},
            {"step": 5, "id": "measure-source-ntfs-minimum", "writes": False, "command": ["<future-windows-ntfs-min-size-probe>", source]},
            {"step": 6, "id": "plan-source-shrink", "writes": True, "command": ["Resize-Partition", "-DriveLetter", source, "-Size", "<future-size>"]},
            {"step": 7, "id": "plan-source-move", "writes": True, "command": ["<future-partition-move-engine>", source, "right", str(increase_bytes)]},
            {"step": 8, "id": "plan-target-grow", "writes": True, "command": ["Resize-Partition", "-DriveLetter", target, "-Size", "<future-size>"]},
            {"step": 9, "id": "verify", "writes": False, "command": ["Get-Partition", "-DiskNumber", "<disk>", "|", "Format-List"]},
            {"step": 10, "id": "detach-vhdx", "writes": False, "command": ["Dismount-DiskImage", "-ImagePath", "<vhdx>"]},
        ],
        "execution": {
            "enabled": False,
            "reason": "Windows NTFS mutation remains dry-run-only until disposable VHDX validation is complete.",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a dry-run Windows NTFS operation plan.")
    parser.add_argument("--image", required=True, help="Disposable VHDX path under lab/test-images.")
    parser.add_argument("--increase-c", default="40G", help="Amount to add to C. Default: 40G.")
    parser.add_argument("--target", default="C", help="Target partition label. Default: C.")
    parser.add_argument("--source", default="E", help="Source partition label. Default: E.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        plan = build_windows_ntfs_plan(Path(args.image), args.increase_c, args.target, args.source)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(plan)
    else:
        print(f"Status: {plan['status']}")
        print(f"Image: {plan['input']['image']}")
        print(f"Execution enabled: {plan['execution']['enabled']}")
        print(f"Blockers: {', '.join(item['id'] for item in plan['blockers'])}")
    return 0 if plan["status"] == "dry-run-only" else 2


if __name__ == "__main__":
    sys.exit(main())
