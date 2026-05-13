#!/usr/bin/env python3
"""Cross-check Python GPT parsing against sgdisk for disposable raw images."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from inspect_image import parse_raw_partition_table
from partitionlab_common import print_json, safety_assessment


SCHEMA_SGDISK_CHECK = "partition-lab.sgdisk-check.v1"


def blocker(blocker_id: str, message: str) -> dict[str, str]:
    return {"id": blocker_id, "message": message}


def run_command(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        return {
            "cmd": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except OSError as exc:
        return {
            "cmd": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }


def parse_sgdisk_print(output: str) -> dict[str, Any]:
    disk: dict[str, Any] = {"partitions": []}
    for line in output.splitlines():
        disk_match = re.match(r"Disk .+: ([0-9]+) sectors, .+", line)
        if disk_match:
            disk["sectors"] = int(disk_match.group(1))
            continue
        sector_match = re.match(r"Sector size \(logical\): ([0-9]+) bytes", line)
        if sector_match:
            disk["sector_size"] = int(sector_match.group(1))
            continue
        alignment_match = re.match(r"Partitions will be aligned on ([0-9]+)-sector boundaries", line)
        if alignment_match:
            disk["alignment_sectors"] = int(alignment_match.group(1))
            continue
        partition_match = re.match(
            r"\s*([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+.+?\s+([0-9A-Fa-f]{4})\s*(.*)$",
            line,
        )
        if partition_match:
            disk["partitions"].append(
                {
                    "number": int(partition_match.group(1)),
                    "start_sector": int(partition_match.group(2)),
                    "end_sector": int(partition_match.group(3)),
                    "code": partition_match.group(4),
                    "name": partition_match.group(5).strip(),
                }
            )
    return disk


def verify_output_blockers(output: str) -> list[dict[str, str]]:
    text = output.lower()
    if "no problems found" in text:
        return []
    if "invalid backup" in text or "secondary" in text or "backup" in text:
        return [blocker("sgdisk-backup-header-mismatch", "sgdisk reported a backup or secondary GPT problem")]
    return [blocker("sgdisk-invalid-gpt", "sgdisk did not report a clean GPT")]


def compare_partitions(raw: dict[str, Any], sgdisk: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    raw_partitions = raw.get("partitions", [])
    sgdisk_partitions = sgdisk.get("partitions", [])
    if len(raw_partitions) != len(sgdisk_partitions):
        blockers.append(blocker("sgdisk-layout-mismatch", "partition count differs between Python parser and sgdisk"))
        return blockers

    by_number = {int(partition["number"]): partition for partition in sgdisk_partitions}
    for raw_partition in raw_partitions:
        number = int(raw_partition["number"])
        sgdisk_partition = by_number.get(number)
        if not sgdisk_partition:
            blockers.append(blocker("sgdisk-layout-mismatch", f"partition {number} is missing from sgdisk output"))
            continue
        if int(raw_partition["start_sector"]) != int(sgdisk_partition["start_sector"]) or int(
            raw_partition["end_sector"]
        ) != int(sgdisk_partition["end_sector"]):
            blockers.append(blocker("sgdisk-layout-mismatch", f"partition {number} sector bounds differ from sgdisk"))
    return blockers


def cross_check_gpt(image: Path, allow_outside_test_images: bool = False) -> dict[str, Any]:
    image = image.resolve(strict=False)
    safety = safety_assessment(image)
    if not safety["under_test_images"] and not allow_outside_test_images:
        raise ValueError("image must be under test-images unless --allow-outside-test-images is set")
    if safety["block_device"] or safety["windows_physical_drive"] or safety["denylisted_system_device"]:
        raise ValueError("refusing block or system device for sgdisk cross-check")
    if not image.exists():
        raise ValueError(f"image not found: {image}")

    sgdisk_path = shutil.which("sgdisk")
    if not sgdisk_path:
        return {
            "schema": SCHEMA_SGDISK_CHECK,
            "image": str(image),
            "status": "blocked",
            "blockers": [blocker("sgdisk-missing", "sgdisk is not installed")],
            "commands": [],
        }

    raw = parse_raw_partition_table(image)
    if not raw or raw.get("partition_table") != "gpt":
        return {
            "schema": SCHEMA_SGDISK_CHECK,
            "image": str(image),
            "status": "blocked",
            "blockers": [blocker("sgdisk-invalid-gpt", "Python parser did not find a GPT raw image")],
            "commands": [],
        }

    print_result = run_command([sgdisk_path, "-p", str(image)])
    verify_result = run_command([sgdisk_path, "-v", str(image)])
    commands = [print_result, verify_result]
    blockers: list[dict[str, str]] = []
    if print_result["returncode"] != 0 or verify_result["returncode"] != 0:
        blockers.append(blocker("sgdisk-unreadable-image", "sgdisk could not read the image cleanly"))

    sgdisk_disk = parse_sgdisk_print(print_result["stdout"])
    blockers.extend(compare_partitions(raw, sgdisk_disk))
    blockers.extend(verify_output_blockers(verify_result["stdout"] + "\n" + verify_result["stderr"]))

    return {
        "schema": SCHEMA_SGDISK_CHECK,
        "image": str(image),
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "python": {
            "partition_table": raw.get("partition_table"),
            "sector_size": raw.get("sector_size"),
            "partitions": raw.get("partitions", []),
        },
        "sgdisk": sgdisk_disk,
        "commands": commands,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-check a disposable raw GPT image with sgdisk.")
    parser.add_argument("--image", required=True, help="Raw image under lab/test-images.")
    parser.add_argument("--allow-outside-test-images", action="store_true", help="Allow read-only inspection outside test-images.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = cross_check_gpt(Path(args.image), args.allow_outside_test_images)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print_json(result)
    else:
        print(f"Image: {result['image']}")
        print(f"Status: {result['status']}")
        if result["blockers"]:
            print(f"Blockers: {', '.join(item['id'] for item in result['blockers'])}")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
