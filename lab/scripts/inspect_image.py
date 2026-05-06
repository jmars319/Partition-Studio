#!/usr/bin/env python3
"""Inspect a disposable raw disk image without mounting it by default."""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from partitionlab_common import safety_assessment, print_json


SECTOR_SIZE = 512


def run_command(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        return {
            "cmd": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except FileNotFoundError as exc:
        return {
            "cmd": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }


def parse_parted_machine(output: str) -> dict[str, Any]:
    disk: dict[str, Any] = {"partitions": [], "free_regions": []}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line == "BYT;":
            continue
        fields = line.rstrip(";").split(":")
        if len(fields) >= 7 and fields[0].startswith("/"):
            disk.update(
                {
                    "path": fields[0],
                    "size": fields[1],
                    "transport": fields[2],
                    "sector_size_logical": fields[3],
                    "sector_size_physical": fields[4],
                    "partition_table": fields[5],
                    "model": fields[6],
                }
            )
            continue
        if len(fields) >= 5:
            item = {
                "number": fields[0],
                "start": fields[1],
                "end": fields[2],
                "size": fields[3],
                "filesystem": fields[4],
                "name": fields[5] if len(fields) > 5 else "",
                "flags": fields[6] if len(fields) > 6 else "",
            }
            if fields[4] == "free":
                disk["free_regions"].append(item)
            elif fields[0].isdigit():
                disk["partitions"].append(item)
    return disk


def detect_filesystem(handle: Any, start_lba: int) -> str | None:
    try:
        original_position = handle.tell()
        handle.seek(start_lba * SECTOR_SIZE + 3)
        marker = handle.read(8)
        handle.seek(original_position)
    except OSError:
        return None
    if marker == b"NTFS    ":
        return "ntfs"
    if marker.startswith(b"MSDOS") or marker.startswith(b"FAT"):
        return "fat"
    return None


def parse_mbr_entry(entry: bytes, number: int, handle: Any) -> dict[str, Any] | None:
    partition_type = entry[4]
    start_lba, sectors = struct.unpack_from("<II", entry, 8)
    if partition_type == 0 or sectors == 0:
        return None
    end_lba = start_lba + sectors - 1
    return {
        "number": number,
        "type": f"0x{partition_type:02x}",
        "start_sector": start_lba,
        "end_sector": end_lba,
        "size_sectors": sectors,
        "size_bytes": sectors * SECTOR_SIZE,
        "filesystem": detect_filesystem(handle, start_lba),
    }


def parse_raw_partition_table(path: Path) -> dict[str, Any] | None:
    """Parse GPT or MBR directly from a raw image file."""
    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            mbr = handle.read(SECTOR_SIZE)
            if len(mbr) < SECTOR_SIZE or mbr[510:512] != b"\x55\xaa":
                return None

            mbr_entries = [
                parse_mbr_entry(mbr[446 + index * 16 : 446 + (index + 1) * 16], index + 1, handle)
                for index in range(4)
            ]
            mbr_entries = [entry for entry in mbr_entries if entry]
            protective = len(mbr_entries) == 1 and mbr_entries[0]["type"] == "0xee"

            if protective:
                handle.seek(SECTOR_SIZE)
                header = handle.read(SECTOR_SIZE)
                if header[0:8] != b"EFI PART":
                    return None
                partition_entry_lba = struct.unpack_from("<Q", header, 72)[0]
                partition_entry_count = struct.unpack_from("<I", header, 80)[0]
                partition_entry_size = struct.unpack_from("<I", header, 84)[0]
                partitions = []
                handle.seek(partition_entry_lba * SECTOR_SIZE)
                for index in range(partition_entry_count):
                    entry = handle.read(partition_entry_size)
                    if len(entry) < 56:
                        break
                    type_guid = uuid.UUID(bytes_le=entry[0:16])
                    if type_guid.int == 0:
                        continue
                    first_lba = struct.unpack_from("<Q", entry, 32)[0]
                    last_lba = struct.unpack_from("<Q", entry, 40)[0]
                    raw_name = entry[56:partition_entry_size].split(b"\x00\x00", 1)[0]
                    if len(raw_name) % 2:
                        raw_name += b"\x00"
                    try:
                        name = raw_name.decode("utf-16le").rstrip("\x00")
                    except UnicodeDecodeError:
                        name = ""
                    partitions.append(
                        {
                            "number": len(partitions) + 1,
                            "name": name,
                            "type_guid": str(type_guid).upper(),
                            "start_sector": first_lba,
                            "end_sector": last_lba,
                            "size_sectors": last_lba - first_lba + 1,
                            "size_bytes": (last_lba - first_lba + 1) * SECTOR_SIZE,
                            "filesystem": detect_filesystem(handle, first_lba),
                        }
                    )
                return {
                    "format": "raw",
                    "partition_table": "gpt",
                    "sector_size": SECTOR_SIZE,
                    "size_bytes": size,
                    "partitions": partitions,
                }

            return {
                "format": "raw",
                "partition_table": "mbr",
                "sector_size": SECTOR_SIZE,
                "size_bytes": size,
                "partitions": mbr_entries,
            }
    except OSError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a raw disk image with the built-in GPT/MBR parser plus optional system tools.")
    parser.add_argument("--image", required=True, help="Path to a disk image. Must be under test-images by default.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--allow-outside-test-images",
        action="store_true",
        help="Allow read-only inspection outside test-images. This does not enable writes.",
    )
    parser.add_argument(
        "--allow-lab-block-device",
        action="store_true",
        help="Allow read-only inspection of a lab block device. System disks are still denied.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target = Path(args.image)
    safety = safety_assessment(target, allow_block_device=args.allow_lab_block_device)
    if safety["denylisted_system_device"]:
        parser.error(f"refusing system block device: {safety['resolved_path']}")
    if (safety["block_device"] or safety["windows_physical_drive"]) and not args.allow_lab_block_device:
        parser.error("refusing block device without --allow-lab-block-device")
    if not safety["under_test_images"] and not args.allow_outside_test_images:
        parser.error("image must be under test-images unless --allow-outside-test-images is set")
    if not target.exists():
        parser.error(f"image not found: {target}")

    commands: list[dict[str, Any]] = []
    parsed: dict[str, Any] = {}
    tool_available = {
        "parted": shutil.which("parted") is not None,
        "sgdisk": shutil.which("sgdisk") is not None,
        "lsblk": shutil.which("lsblk") is not None,
    }

    if tool_available["parted"]:
        command = ["parted", "-m", "-s", str(target), "unit", "s", "print", "free"]
        result = run_command(command)
        commands.append(result)
        if result["returncode"] == 0:
            parsed["parted"] = parse_parted_machine(result["stdout"])

    raw_partition_table = parse_raw_partition_table(target)
    if raw_partition_table:
        parsed["raw"] = raw_partition_table

    if tool_available["sgdisk"]:
        commands.append(run_command(["sgdisk", "-p", str(target)]))

    if safety["block_device"] and tool_available["lsblk"]:
        commands.append(run_command(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINTS", str(target)]))
        try:
            lsblk_result = commands[-1]
            if lsblk_result["returncode"] == 0:
                parsed["lsblk"] = json.loads(lsblk_result["stdout"])
        except json.JSONDecodeError:
            pass

    inspection = {
        "schema": "partition-lab.image-inspection.v1",
        "target": str(target),
        "safety": safety,
        "tools": tool_available,
        "parsed": parsed,
        "commands": commands,
    }

    if args.json:
        print_json(inspection)
    else:
        print(f"Target: {target}")
        print(f"Safety accepted for read-only inspection: {safety['accepted'] or args.allow_outside_test_images}")
        if parsed.get("parted"):
            disk = parsed["parted"]
            print(f"Partition table: {disk.get('partition_table', 'unknown')}")
            print("Partitions:")
            for partition in disk.get("partitions", []):
                print(
                    f"  {partition.get('number')}: start={partition.get('start')} "
                    f"end={partition.get('end')} size={partition.get('size')} fs={partition.get('filesystem')}"
                )
            if disk.get("free_regions"):
                print("Free regions:")
                for region in disk["free_regions"]:
                    print(f"  start={region.get('start')} end={region.get('end')} size={region.get('size')}")
        elif parsed.get("raw"):
            disk = parsed["raw"]
            print(f"Partition table: {disk.get('partition_table', 'unknown')}")
            print("Partitions:")
            for partition in disk.get("partitions", []):
                print(
                    f"  {partition.get('number')}: start={partition.get('start_sector')} "
                    f"end={partition.get('end_sector')} size={partition.get('size_bytes')} fs={partition.get('filesystem')}"
                )
        else:
            print("No parsed partition data available. Install parted or use a raw image with a GPT/MBR table.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
