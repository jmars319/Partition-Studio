#!/usr/bin/env python3
"""Inspect a disposable raw disk image without mounting it by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from pathlib import Path
from typing import Any

from partitionlab_common import SCHEMA_LAYOUT, safety_assessment, print_json


SECTOR_SIZE = 512
MANIFEST_SCHEMA = "partition-lab.image-manifest.v1"


def issue(issue_id: str, severity: str, message: str) -> dict[str, str]:
    return {"id": issue_id, "severity": severity, "message": message}


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


def gpt_blocker(issue_id: str, message: str) -> dict[str, str]:
    return issue(issue_id, "blocking", message)


def gpt_header_crc_ok(header: bytes) -> bool:
    if len(header) < 92:
        return False
    header_size = struct.unpack_from("<I", header, 12)[0]
    if header_size < 92 or header_size > len(header):
        return False
    stored_crc = struct.unpack_from("<I", header, 16)[0]
    candidate = bytearray(header[:header_size])
    struct.pack_into("<I", candidate, 16, 0)
    return (zlib.crc32(candidate) & 0xFFFFFFFF) == stored_crc


def validate_gpt(
    handle: Any,
    header: bytes,
    size: int,
    partition_entries: bytes,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    total_sectors = size // SECTOR_SIZE
    if not gpt_header_crc_ok(header):
        issues.append(gpt_blocker("gpt-primary-header-crc-mismatch", "primary GPT header CRC does not match"))

    backup_lba = struct.unpack_from("<Q", header, 32)[0]
    entries_crc = struct.unpack_from("<I", header, 88)[0]
    actual_entries_crc = zlib.crc32(partition_entries) & 0xFFFFFFFF
    if actual_entries_crc != entries_crc:
        issues.append(gpt_blocker("gpt-entry-crc-mismatch", "GPT partition-entry array CRC does not match"))

    if backup_lba >= total_sectors:
        issues.append(gpt_blocker("gpt-backup-header-out-of-range", "backup GPT header points outside the image"))
        return issues

    handle.seek(backup_lba * SECTOR_SIZE)
    backup_header = handle.read(SECTOR_SIZE)
    if len(backup_header) < SECTOR_SIZE or backup_header[0:8] != b"EFI PART":
        issues.append(gpt_blocker("gpt-backup-header-invalid", "backup GPT header is missing or invalid"))
        return issues
    if not gpt_header_crc_ok(backup_header):
        issues.append(gpt_blocker("gpt-backup-header-crc-mismatch", "backup GPT header CRC does not match"))
    backup_current_lba = struct.unpack_from("<Q", backup_header, 24)[0]
    backup_backup_lba = struct.unpack_from("<Q", backup_header, 32)[0]
    if backup_current_lba != backup_lba or backup_backup_lba != 1:
        issues.append(gpt_blocker("gpt-backup-header-location-mismatch", "backup GPT header location fields are inconsistent"))
    return issues


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
                partition_entries = handle.read(partition_entry_count * partition_entry_size)
                for index in range(partition_entry_count):
                    start = index * partition_entry_size
                    entry = partition_entries[start : start + partition_entry_size]
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
                    "gpt_validation_issues": validate_gpt(handle, header, size, partition_entries),
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


def manifest_path_for_image(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".manifest.json")


def load_image_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = manifest_path_for_image(path)
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"expected manifest schema {MANIFEST_SCHEMA}")
    return manifest


def validate_image_manifest(path: Path, raw: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = list(raw.get("gpt_validation_issues", []))
    manifest_disk = manifest.get("disk")
    if not isinstance(manifest.get("image_id"), str) or not manifest["image_id"]:
        issues.append(issue("manifest-image-id-missing", "error", "manifest.image_id must be a non-empty string"))
    if not isinstance(manifest_disk, dict):
        return [*issues, issue("manifest-disk-missing", "error", "manifest.disk is required")]

    if manifest.get("format") != "raw":
        issues.append(issue("manifest-format", "error", "manifest.format must be raw"))
    manifest_image = manifest.get("image")
    if isinstance(manifest_image, str) and Path(manifest_image).name != path.name:
        issues.append(issue("manifest-image-path-mismatch", "warning", "manifest image path points at a different filename"))
    if manifest_disk.get("label") != raw.get("partition_table"):
        issues.append(issue("manifest-partition-table-mismatch", "error", "manifest disk label does not match parsed partition table"))
    if manifest_disk.get("sector_size") != raw.get("sector_size"):
        issues.append(issue("manifest-sector-size-mismatch", "error", "manifest sector size does not match parsed image"))
    if manifest_disk.get("size_bytes") != raw.get("size_bytes"):
        issues.append(issue("manifest-size-mismatch", "error", "manifest disk size does not match parsed image"))

    manifest_partitions = manifest_disk.get("partitions")
    if not isinstance(manifest_partitions, list):
        return [*issues, issue("manifest-partitions-missing", "error", "manifest.disk.partitions must be a list")]
    if len(manifest_partitions) != len(raw.get("partitions", [])):
        issues.append(issue("manifest-partition-count-mismatch", "error", "manifest partition count does not match parsed image"))

    raw_by_number = {int(partition["number"]): partition for partition in raw.get("partitions", [])}
    labels = set()
    for partition in manifest_partitions:
        if not isinstance(partition, dict) or "number" not in partition:
            issues.append(issue("manifest-partition-invalid", "error", "manifest partition entries must include number"))
            continue
        number = int(partition["number"])
        label = str(partition.get("label") or partition.get("name") or number).upper()
        labels.add(label)
        raw_partition = raw_by_number.get(number)
        if not raw_partition:
            issues.append(issue("manifest-partition-missing-in-image", "error", f"partition {number} is not present in parsed image"))
            continue
        for field in ("start_sector", "end_sector"):
            if int(partition.get(field, -1)) != int(raw_partition[field]):
                issues.append(issue("manifest-partition-bounds-mismatch", "error", f"partition {number} {field} does not match parsed image"))
        size_bytes = (int(partition["end_sector"]) - int(partition["start_sector"]) + 1) * int(raw.get("sector_size", SECTOR_SIZE))
        used_bytes = partition.get("used_bytes")
        free_bytes = partition.get("free_bytes")
        if not isinstance(used_bytes, int) or used_bytes < 0:
            issues.append(issue("manifest-used-bytes-invalid", "error", f"partition {number} used_bytes must be non-negative"))
        if not isinstance(free_bytes, int) or free_bytes < 0:
            issues.append(issue("manifest-free-bytes-invalid", "error", f"partition {number} free_bytes must be non-negative"))
        if isinstance(used_bytes, int) and isinstance(free_bytes, int) and used_bytes + free_bytes > size_bytes:
            issues.append(issue("manifest-capacity-invalid", "error", f"partition {number} used_bytes plus free_bytes exceeds partition size"))
        if partition.get("filesystem_state") not in {None, "clean"}:
            issues.append(issue("manifest-filesystem-state", "blocking", f"partition {label} filesystem state is {partition.get('filesystem_state')}"))
        if partition.get("encrypted"):
            issues.append(issue("manifest-encrypted", "blocking", f"partition {label} is marked encrypted"))

    workflow = manifest.get("workflow")
    if isinstance(workflow, dict):
        for label_field in ("target_label", "source_label"):
            label = str(workflow.get(label_field, "")).upper()
            if label not in labels:
                issues.append(issue("manifest-workflow-label-missing", "error", f"workflow {label_field} does not match a partition label"))
    else:
        issues.append(issue("manifest-workflow-missing", "error", "manifest.workflow is required"))

    operation_state = manifest_disk.get("operation_state")
    if operation_state:
        issues.append(issue("manifest-operation-state", "blocking", f"disk operation_state is {operation_state}"))

    return issues


def read_payload_marker(path: Path, partition: dict[str, Any], marker: dict[str, Any]) -> dict[str, Any]:
    offset = int(partition["start_sector"]) * SECTOR_SIZE + int(marker["offset_bytes"])
    size = int(marker["size_bytes"])
    with path.open("rb") as handle:
        handle.seek(offset)
        payload = handle.read(size)
    actual_hash = hashlib.sha256(payload).hexdigest()
    return {
        **marker,
        "actual_sha256": actual_hash,
        "hash_ok": actual_hash == marker.get("sha256"),
    }


def free_regions(partitions: list[dict[str, Any]], total_sectors: int) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    previous_end = -1
    for partition in sorted(partitions, key=lambda item: int(item["start_sector"])):
        start = int(partition["start_sector"])
        if start > previous_end + 1:
            regions.append(
                {
                    "start_sector": previous_end + 1,
                    "end_sector": start - 1,
                    "size_bytes": (start - previous_end - 1) * SECTOR_SIZE,
                }
            )
        previous_end = int(partition["end_sector"])
    if previous_end + 1 < total_sectors:
        regions.append(
            {
                "start_sector": previous_end + 1,
                "end_sector": total_sectors - 1,
                "size_bytes": (total_sectors - previous_end - 1) * SECTOR_SIZE,
            }
        )
    return [region for region in regions if region["size_bytes"] > 0]


def normalize_raw_layout(path: Path, raw: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        raise ValueError(f"missing image manifest: {manifest_path_for_image(path)}")
    if raw.get("format") != "raw":
        raise ValueError("layout normalization currently supports raw image inspection only")
    validation_issues = validate_image_manifest(path, raw, manifest)
    structural_errors = [item for item in validation_issues if item["severity"] == "error"]
    if structural_errors:
        raise ValueError("; ".join(item["message"] for item in structural_errors))

    manifest_disk = manifest.get("disk")
    if not isinstance(manifest_disk, dict):
        raise ValueError("image manifest is missing disk metadata")
    manifest_partitions = {
        int(partition["number"]): partition
        for partition in manifest_disk.get("partitions", [])
        if isinstance(partition, dict) and "number" in partition
    }

    normalized_partitions: list[dict[str, Any]] = []
    for raw_partition in raw.get("partitions", []):
        number = int(raw_partition["number"])
        metadata = manifest_partitions.get(number)
        if not metadata:
            raise ValueError(f"image manifest is missing metadata for partition {number}")

        label = str(metadata.get("label") or metadata.get("name") or raw_partition.get("name") or number)
        filesystem = (
            metadata.get("intended_filesystem")
            or raw_partition.get("filesystem")
            or metadata.get("filesystem")
            or "unknown"
        )
        files = list(metadata.get("files") or [])
        marker = metadata.get("payload_marker")
        payload_marker = None
        if isinstance(marker, dict):
            payload_marker = read_payload_marker(path, raw_partition, marker)
            if not payload_marker["hash_ok"]:
                validation_issues.append(
                    issue("payload-marker-hash-mismatch", "blocking", f"{label} payload marker hash does not match the manifest")
                )
            files.append(f"/payload-markers/{label}-{marker.get('payload_id', 'unknown')}.bin")

        partition = {
            "number": number,
            "label": label,
            "name": str(metadata.get("name") or label),
            "type": metadata.get("type") or raw_partition.get("type_guid") or raw_partition.get("type") or "unknown",
            "start_sector": int(raw_partition["start_sector"]),
            "end_sector": int(raw_partition["end_sector"]),
            "filesystem": str(filesystem).lower(),
            "filesystem_state": metadata.get("filesystem_state", "clean"),
            "mountpoint": metadata.get("mountpoint"),
            "encrypted": bool(metadata.get("encrypted", False)),
            "used_bytes": int(metadata.get("used_bytes", 0)),
            "free_bytes": int(metadata.get("free_bytes", 0)),
            "minimum_size_bytes": int(metadata.get("minimum_size_bytes", metadata.get("used_bytes", 0))),
            "files": files,
        }
        if payload_marker:
            partition["payload_marker"] = payload_marker
        normalized_partitions.append(partition)

    total_sectors = int(raw["size_bytes"]) // int(raw.get("sector_size", SECTOR_SIZE))
    layout = {
        "schema": SCHEMA_LAYOUT,
        "scenario": manifest.get("scenario"),
        "mode": "raw-geometry",
        "description": "Normalized from a disposable raw image inspection.",
        "manifest_validation": {
            "status": "blocked"
            if any(item["severity"] == "blocking" for item in validation_issues)
            else "review"
            if any(item["severity"] == "warning" for item in validation_issues)
            else "pass",
            "issues": validation_issues,
        },
        "image": {
            "path": str(path.resolve(strict=False)),
            "manifest": str(manifest_path_for_image(path).resolve(strict=False)),
            "format": "raw",
            "image_id": manifest.get("image_id"),
        },
        "workflow": manifest.get("workflow", {}),
        "disk": {
            "id": manifest.get("image_id") or path.stem,
            "path": str(path.resolve(strict=False)),
            "label": raw.get("partition_table", manifest_disk.get("label", "unknown")),
            "sector_size": int(raw.get("sector_size", manifest_disk.get("sector_size", SECTOR_SIZE))),
            "alignment_sectors": int(manifest_disk.get("alignment_sectors", 2048)),
            "size_bytes": int(raw["size_bytes"]),
            "operation_state": manifest_disk.get("operation_state"),
            "partitions": sorted(normalized_partitions, key=lambda item: item["start_sector"]),
            "free_regions": free_regions(normalized_partitions, total_sectors),
        },
    }
    if layout["disk"]["operation_state"] is None:
        del layout["disk"]["operation_state"]
    return layout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect a raw disk image with the built-in GPT/MBR parser plus optional system tools.")
    parser.add_argument("--image", required=True, help="Path to a disk image. Must be under test-images by default.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--layout-json", action="store_true", help="Emit normalized partition-lab.layout.v1 JSON.")
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
    manifest: dict[str, Any] | None = None
    tool_available = {
        "parted": shutil.which("parted") is not None,
        "sgdisk": shutil.which("sgdisk") is not None,
        "lsblk": shutil.which("lsblk") is not None,
    }

    try:
        manifest = load_image_manifest(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.layout_json:
            parser.error(str(exc))
        parsed["manifest_error"] = str(exc)

    if tool_available["parted"]:
        command = ["parted", "-m", "-s", str(target), "unit", "s", "print", "free"]
        result = run_command(command)
        commands.append(result)
        if result["returncode"] == 0:
            parsed["parted"] = parse_parted_machine(result["stdout"])

    raw_partition_table = parse_raw_partition_table(target)
    if raw_partition_table:
        parsed["raw"] = raw_partition_table
    if manifest:
        parsed["manifest"] = {
            "path": str(manifest_path_for_image(target)),
            "schema": manifest.get("schema"),
            "scenario": manifest.get("scenario"),
            "image_id": manifest.get("image_id"),
        }

    if args.layout_json:
        if not raw_partition_table:
            parser.error("no raw GPT/MBR partition table was parsed")
        try:
            print_json(normalize_raw_layout(target, raw_partition_table, manifest))
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        return 0

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
