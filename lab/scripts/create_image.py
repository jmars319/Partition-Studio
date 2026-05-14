#!/usr/bin/env python3
"""Create a cross-platform disposable raw disk image with C and E partitions.

This is the portable fallback path. It writes partition tables only; it does not
format NTFS. On Windows, use create-test-image.ps1 for real NTFS-formatted VHDX
images.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from partitionlab_common import TEST_IMAGES_DIR, parse_size, path_is_under


SECTOR_SIZE = 512
ALIGNMENT_SECTORS = 2048
MICROSOFT_BASIC_DATA_GUID = uuid.UUID("EBD0A0A2-B9E5-4433-87C0-68B6B72699C7")
GPT_PARTITION_ENTRY_SIZE = 128
GPT_PARTITION_ENTRY_COUNT = 128
PAYLOAD_MARKER_OFFSET_BYTES = 4096
PAYLOAD_MARKER_SIZE_BYTES = 4096

DEFAULT_IMAGE_CONFIG: dict[str, Any] = {
    "disk_size": "12GiB",
    "c_size": "4GiB",
    "e_size": "7GiB",
    "c_used": "3500MiB",
    "e_used": "2GiB",
    "min_source_free_after": "1GiB",
    "partition_table": "gpt",
    "layout": "adjacent",
    "c_filesystem_state": "clean",
    "e_filesystem_state": "clean",
    "c_encrypted": False,
    "e_encrypted": False,
    "operation_state": None,
    "corrupt_payload_marker": False,
    "malformed_manifest": False,
    "corrupt_primary_gpt_header": False,
    "corrupt_backup_gpt_header": False,
    "corrupt_gpt_entry_crc": False,
    "truncate_image": False,
    "manifest_sector_size_mismatch": False,
    "manifest_disk_size_mismatch": False,
    "manifest_partition_bounds_mismatch": False,
}

SCENARIO_PRESETS: dict[str, dict[str, Any]] = {
    "normal-c-e-layout": {},
    "gpt-layout": {},
    "e-has-insufficient-free-space": {
        "e_used": "6500MiB",
    },
    "mbr-layout": {
        "partition_table": "mbr",
    },
    "non-adjacent-free-space": {
        "layout": "non-adjacent",
    },
    "unaligned-layout": {
        "layout": "unaligned",
    },
    "dirty-filesystem-placeholder": {
        "e_filesystem_state": "dirty",
    },
    "encrypted-filesystem-placeholder": {
        "e_encrypted": True,
    },
    "interrupted-operation-placeholder": {
        "operation_state": "interrupted-move",
    },
    "corrupted-payload-marker": {
        "corrupt_payload_marker": True,
    },
    "malformed-manifest": {
        "malformed_manifest": True,
    },
    "primary-gpt-header-corrupt": {
        "corrupt_primary_gpt_header": True,
    },
    "backup-gpt-header-corrupt": {
        "corrupt_backup_gpt_header": True,
    },
    "gpt-entry-crc-mismatch": {
        "corrupt_gpt_entry_crc": True,
    },
    "overlapping-partitions": {
        "layout": "overlap",
    },
    "truncated-image": {
        "truncate_image": True,
    },
    "manifest-sector-size-mismatch": {
        "manifest_sector_size_mismatch": True,
    },
    "manifest-disk-size-mismatch": {
        "manifest_disk_size_mismatch": True,
    },
    "manifest-partition-bounds-mismatch": {
        "manifest_partition_bounds_mismatch": True,
    },
}


def align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def size_to_sectors(value: str) -> int:
    size = parse_size(value)
    if size % SECTOR_SIZE:
        raise ValueError(f"size must be sector-aligned: {value}")
    return size // SECTOR_SIZE


def partition_entry(
    type_guid: uuid.UUID,
    first_lba: int,
    last_lba: int,
    name: str,
) -> bytes:
    entry = bytearray(GPT_PARTITION_ENTRY_SIZE)
    unique_guid = uuid.uuid5(uuid.NAMESPACE_URL, f"partition-lab:{name}:{first_lba}:{last_lba}")
    entry[0:16] = type_guid.bytes_le
    entry[16:32] = unique_guid.bytes_le
    struct.pack_into("<QQQ", entry, 32, first_lba, last_lba, 0)
    encoded_name = name.encode("utf-16le")[:72]
    entry[56 : 56 + len(encoded_name)] = encoded_name
    return bytes(entry)


def protective_mbr(total_sectors: int) -> bytes:
    sector = bytearray(SECTOR_SIZE)
    sector[446 + 4] = 0xEE
    struct.pack_into("<II", sector, 446 + 8, 1, min(total_sectors - 1, 0xFFFFFFFF))
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


def conventional_mbr(partitions: list[dict[str, Any]]) -> bytes:
    sector = bytearray(SECTOR_SIZE)
    for index, partition in enumerate(partitions[:4]):
        offset = 446 + index * 16
        sector[offset] = 0x00
        sector[offset + 4] = 0x07
        struct.pack_into(
            "<II",
            sector,
            offset + 8,
            partition["start_sector"],
            partition["end_sector"] - partition["start_sector"] + 1,
        )
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


def gpt_header(
    total_sectors: int,
    current_lba: int,
    backup_lba: int,
    first_usable_lba: int,
    last_usable_lba: int,
    disk_guid: uuid.UUID,
    partition_entries_lba: int,
    partition_entries_crc: int,
) -> bytes:
    header_size = 92
    header = bytearray(SECTOR_SIZE)
    header[0:8] = b"EFI PART"
    struct.pack_into("<I", header, 8, 0x00010000)
    struct.pack_into("<I", header, 12, header_size)
    struct.pack_into("<I", header, 16, 0)
    struct.pack_into("<I", header, 20, 0)
    struct.pack_into("<Q", header, 24, current_lba)
    struct.pack_into("<Q", header, 32, backup_lba)
    struct.pack_into("<Q", header, 40, first_usable_lba)
    struct.pack_into("<Q", header, 48, last_usable_lba)
    header[56:72] = disk_guid.bytes_le
    struct.pack_into("<Q", header, 72, partition_entries_lba)
    struct.pack_into("<I", header, 80, GPT_PARTITION_ENTRY_COUNT)
    struct.pack_into("<I", header, 84, GPT_PARTITION_ENTRY_SIZE)
    struct.pack_into("<I", header, 88, partition_entries_crc)
    crc = zlib.crc32(header[:header_size]) & 0xFFFFFFFF
    struct.pack_into("<I", header, 16, crc)
    return bytes(header)


def build_partitions(c_size: str, e_size: str, layout: str = "adjacent") -> list[dict[str, Any]]:
    c_sectors = size_to_sectors(c_size)
    e_sectors = size_to_sectors(e_size)
    c_start = ALIGNMENT_SECTORS + 1 if layout == "unaligned" else ALIGNMENT_SECTORS
    c_end = c_start + c_sectors - 1
    if layout == "non-adjacent":
        e_start = align_up(c_end + 1, ALIGNMENT_SECTORS) + ALIGNMENT_SECTORS
    elif layout == "unaligned":
        e_start = c_end + 1
    elif layout == "overlap":
        e_start = c_end - ALIGNMENT_SECTORS + 1
    else:
        e_start = align_up(c_end + 1, ALIGNMENT_SECTORS)
    e_end = e_start + e_sectors - 1
    return [
        {"number": 1, "label": "C", "start_sector": c_start, "end_sector": c_end},
        {"number": 2, "label": "E", "start_sector": e_start, "end_sector": e_end},
    ]


def write_gpt_image(path: Path, disk_size: int, partitions: list[dict[str, Any]]) -> None:
    total_sectors = disk_size // SECTOR_SIZE
    entry_array_sectors = (GPT_PARTITION_ENTRY_COUNT * GPT_PARTITION_ENTRY_SIZE + SECTOR_SIZE - 1) // SECTOR_SIZE
    first_usable_lba = 2 + entry_array_sectors
    last_usable_lba = total_sectors - entry_array_sectors - 2
    if partitions[-1]["end_sector"] > last_usable_lba:
        raise ValueError("partitions do not fit within GPT usable space")

    entries = bytearray(entry_array_sectors * SECTOR_SIZE)
    for index, partition in enumerate(partitions):
        entry = partition_entry(
            MICROSOFT_BASIC_DATA_GUID,
            partition["start_sector"],
            partition["end_sector"],
            partition["label"],
        )
        start = index * GPT_PARTITION_ENTRY_SIZE
        entries[start : start + GPT_PARTITION_ENTRY_SIZE] = entry

    entries_crc = zlib.crc32(entries) & 0xFFFFFFFF
    disk_guid = uuid.uuid5(uuid.NAMESPACE_URL, f"partition-lab:{path.name}:{disk_size}")

    primary_header = gpt_header(
        total_sectors,
        1,
        total_sectors - 1,
        first_usable_lba,
        last_usable_lba,
        disk_guid,
        2,
        entries_crc,
    )
    backup_entries_lba = total_sectors - entry_array_sectors - 1
    backup_header = gpt_header(
        total_sectors,
        total_sectors - 1,
        1,
        first_usable_lba,
        last_usable_lba,
        disk_guid,
        backup_entries_lba,
        entries_crc,
    )

    with path.open("r+b") as handle:
        handle.seek(0)
        handle.write(protective_mbr(total_sectors))
        handle.seek(SECTOR_SIZE)
        handle.write(primary_header)
        handle.seek(2 * SECTOR_SIZE)
        handle.write(entries)
        handle.seek(backup_entries_lba * SECTOR_SIZE)
        handle.write(entries)
        handle.seek((total_sectors - 1) * SECTOR_SIZE)
        handle.write(backup_header)


def write_mbr_image(path: Path, disk_size: int, partitions: list[dict[str, Any]]) -> None:
    total_sectors = disk_size // SECTOR_SIZE
    if partitions[-1]["end_sector"] >= total_sectors:
        raise ValueError("partitions do not fit within disk")
    with path.open("r+b") as handle:
        handle.seek(0)
        handle.write(conventional_mbr(partitions))


def create_sparse_file(path: Path, disk_size: int) -> None:
    with path.open("wb") as handle:
        handle.truncate(disk_size)


def partition_size_bytes(partition: dict[str, Any]) -> int:
    return (partition["end_sector"] - partition["start_sector"] + 1) * SECTOR_SIZE


def marker_payload(image_id: str, partition: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    payload_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{image_id}:{partition['label']}:{partition['start_sector']}"))
    content = {
        "schema": "partition-lab.payload-marker.v1",
        "image_id": image_id,
        "payload_id": payload_id,
        "partition_number": partition["number"],
        "label": partition["label"],
    }
    raw = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(raw) > PAYLOAD_MARKER_SIZE_BYTES:
        raise ValueError("payload marker is larger than reserved marker size")
    marker = raw + (b"\0" * (PAYLOAD_MARKER_SIZE_BYTES - len(raw)))
    return marker, {
        "schema": "partition-lab.payload-marker.v1",
        "payload_id": payload_id,
        "offset_bytes": PAYLOAD_MARKER_OFFSET_BYTES,
        "size_bytes": PAYLOAD_MARKER_SIZE_BYTES,
        "sha256": hashlib.sha256(marker).hexdigest(),
    }


def write_payload_markers(path: Path, image_id: str, partitions: list[dict[str, Any]]) -> None:
    with path.open("r+b") as handle:
        for partition in partitions:
            if partition_size_bytes(partition) <= PAYLOAD_MARKER_OFFSET_BYTES + PAYLOAD_MARKER_SIZE_BYTES:
                raise ValueError(f"partition {partition['label']} is too small for payload marker")
            marker, metadata = marker_payload(image_id, partition)
            handle.seek(partition["start_sector"] * SECTOR_SIZE + PAYLOAD_MARKER_OFFSET_BYTES)
            handle.write(marker)
            partition["payload_marker"] = metadata


def write_manifest(
    path: Path,
    scenario: str,
    image_id: str,
    partition_table: str,
    disk_size: int,
    partitions: list[dict[str, Any]],
    c_used_bytes: int,
    e_used_bytes: int,
    min_source_free_after_bytes: int,
    config: dict[str, Any],
) -> None:
    usage_by_label = {
        "C": c_used_bytes,
        "E": e_used_bytes,
    }
    manifest = {
        "schema": "partition-lab.image-manifest.v1",
        "manifest_version": 2,
        "scenario": scenario,
        "scenario_preset": scenario if scenario in SCENARIO_PRESETS else None,
        "image_id": image_id,
        "image": str(path),
        "format": "raw",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation": {
            "status": "unsafe" if config.get("operation_state") else "created",
            "blockers": [config["operation_state"]] if config.get("operation_state") else [],
        },
        "workflow": {
            "target_label": "C",
            "source_label": "E",
            "minimum_source_free_after_bytes": min_source_free_after_bytes,
        },
        "disk": {
            "label": partition_table,
            "sector_size": SECTOR_SIZE,
            "alignment_sectors": ALIGNMENT_SECTORS,
            "size_bytes": disk_size,
            **({"operation_state": config["operation_state"]} if config.get("operation_state") else {}),
            "partitions": [
                {
                    **partition,
                    "type": "msftdata",
                    "filesystem": "raw-geometry-placeholder",
                    "intended_filesystem": "ntfs",
                    "filesystem_state": config[f"{partition['label'].lower()}_filesystem_state"],
                    "mountpoint": None,
                    "encrypted": bool(config[f"{partition['label'].lower()}_encrypted"]),
                    "used_bytes": usage_by_label.get(partition["label"], 0),
                    "free_bytes": partition_size_bytes(partition) - usage_by_label.get(partition["label"], 0),
                    "minimum_size_bytes": usage_by_label.get(partition["label"], 0) + min_source_free_after_bytes,
                }
                for partition in partitions
            ],
        },
    }
    with path.with_suffix(path.suffix + ".manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def write_malformed_manifest(path: Path, scenario: str) -> None:
    manifest = {
        "schema": "partition-lab.image-manifest.malformed",
        "scenario": scenario,
        "error": "This intentionally malformed manifest is used by lab refusal tests.",
    }
    with path.with_suffix(path.suffix + ".manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def corrupt_payload_marker(path: Path, partition: dict[str, Any]) -> None:
    marker = partition.get("payload_marker")
    if not isinstance(marker, dict):
        raise ValueError("payload marker metadata is missing")
    with path.open("r+b") as handle:
        handle.seek(partition["start_sector"] * SECTOR_SIZE + int(marker["offset_bytes"]))
        handle.write(b"corrupted-payload-marker")


def corrupt_primary_gpt_header(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.seek(SECTOR_SIZE)
        handle.write(b"BROKEN!!")


def corrupt_backup_gpt_header(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.seek(path.stat().st_size - SECTOR_SIZE)
        handle.write(b"BROKEN!!")


def corrupt_gpt_entry_crc(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.seek(SECTOR_SIZE + 88)
        handle.write(b"\x00\x00\x00\x00")


def truncate_image(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.truncate(path.stat().st_size - SECTOR_SIZE)


def mutate_manifest(path: Path, config: dict[str, Any]) -> None:
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    disk = manifest["disk"]
    if config["manifest_sector_size_mismatch"]:
        disk["sector_size"] = 4096
    if config["manifest_disk_size_mismatch"]:
        disk["size_bytes"] = int(disk["size_bytes"]) + SECTOR_SIZE
    if config["manifest_partition_bounds_mismatch"]:
        disk["partitions"][1]["start_sector"] = int(disk["partitions"][1]["start_sector"]) + 1
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    config = dict(DEFAULT_IMAGE_CONFIG)
    config.update(SCENARIO_PRESETS.get(args.scenario, {}))
    for key in (
        "disk_size",
        "c_size",
        "e_size",
        "c_used",
        "e_used",
        "min_source_free_after",
        "partition_table",
        "layout",
        "c_filesystem_state",
        "e_filesystem_state",
        "operation_state",
    ):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    if args.c_encrypted:
        config["c_encrypted"] = True
    if args.e_encrypted:
        config["e_encrypted"] = True
    if args.corrupt_payload_marker:
        config["corrupt_payload_marker"] = True
    if args.malformed_manifest:
        config["malformed_manifest"] = True
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a cross-platform raw tenra Partition Lab disk image.")
    parser.add_argument("--scenario", default="normal-c-e-layout", help="Scenario name used for default filename.")
    parser.add_argument("--output", help="Output image path. Must be under test-images by default.")
    parser.add_argument("--disk-size", help="Disk image size. Default: 12GiB.")
    parser.add_argument("--c-size", help="C partition size. Default: 4GiB.")
    parser.add_argument("--e-size", help="E partition size. Default: 7GiB.")
    parser.add_argument("--c-used", help="Modeled used bytes on C. Default: 3500MiB.")
    parser.add_argument("--e-used", help="Modeled used bytes on E. Default: 2GiB.")
    parser.add_argument(
        "--min-source-free-after",
        help="Modeled minimum free bytes to preserve on E after shrink. Default: 1GiB.",
    )
    parser.add_argument("--partition-table", choices=("gpt", "mbr"), help="Partition table. Default: gpt.")
    parser.add_argument("--layout", choices=("adjacent", "non-adjacent", "unaligned", "overlap"), help="Partition geometry layout.")
    parser.add_argument("--c-filesystem-state", choices=("clean", "dirty"), help="Modeled C filesystem state.")
    parser.add_argument("--e-filesystem-state", choices=("clean", "dirty"), help="Modeled E filesystem state.")
    parser.add_argument("--c-encrypted", action="store_true", help="Mark C encrypted in the manifest.")
    parser.add_argument("--e-encrypted", action="store_true", help="Mark E encrypted in the manifest.")
    parser.add_argument("--operation-state", help="Mark the disk with an unsafe operation state.")
    parser.add_argument("--corrupt-payload-marker", action="store_true", help="Corrupt E's payload marker after manifest creation.")
    parser.add_argument("--malformed-manifest", action="store_true", help="Write an intentionally malformed manifest.")
    parser.add_argument("--force", action="store_true", help="Replace an existing image.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing the image.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = build_config(args)
        disk_size = parse_size(config["disk_size"])
        c_used_bytes = parse_size(config["c_used"])
        e_used_bytes = parse_size(config["e_used"])
        min_source_free_after_bytes = parse_size(config["min_source_free_after"])
        if disk_size % SECTOR_SIZE:
            raise ValueError("--disk-size must be sector-aligned")
        output = Path(args.output) if args.output else TEST_IMAGES_DIR / f"{args.scenario}.raw.img"
        output = output.resolve(strict=False)
        TEST_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if not path_is_under(TEST_IMAGES_DIR, output):
            raise ValueError(f"output must be under {TEST_IMAGES_DIR}")
        if output.exists() and not args.force:
            raise ValueError(f"output already exists; use --force: {output}")
        partitions = build_partitions(config["c_size"], config["e_size"], config["layout"])
        if partitions[-1]["end_sector"] >= disk_size // SECTOR_SIZE:
            raise ValueError("C and E partitions do not fit in the requested disk image")
        for partition, used_bytes in ((partitions[0], c_used_bytes), (partitions[1], e_used_bytes)):
            if used_bytes >= partition_size_bytes(partition):
                raise ValueError(f"{partition['label']} modeled used bytes must be smaller than the partition")
        image_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"partition-lab:{args.scenario}:{output.name}:{disk_size}"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    actions = [
        f"create sparse raw image: {output}",
        f"write {config['partition_table'].upper()} partition table",
        "write deterministic payload markers",
        "write malformed manifest JSON" if config["malformed_manifest"] else "write manifest JSON",
    ]
    if config["corrupt_payload_marker"]:
        actions.append("corrupt E payload marker")
    for flag, action in (
        ("corrupt_primary_gpt_header", "corrupt primary GPT header"),
        ("corrupt_backup_gpt_header", "corrupt backup GPT header"),
        ("corrupt_gpt_entry_crc", "corrupt GPT entry CRC"),
        ("truncate_image", "truncate image by one sector"),
        ("manifest_sector_size_mismatch", "mutate manifest sector size"),
        ("manifest_disk_size_mismatch", "mutate manifest disk size"),
        ("manifest_partition_bounds_mismatch", "mutate manifest partition bounds"),
    ):
        if config[flag]:
            actions.append(action)
    for action in actions:
        print(f"+ {action}")
    if args.dry_run:
        return 0

    if output.exists():
        output.unlink()
    create_sparse_file(output, disk_size)
    if config["partition_table"] == "gpt":
        write_gpt_image(output, disk_size, partitions)
    else:
        write_mbr_image(output, disk_size, partitions)
    write_payload_markers(output, image_id, partitions)
    if config["malformed_manifest"]:
        write_malformed_manifest(output, args.scenario)
    else:
        write_manifest(
            output,
            args.scenario,
            image_id,
            config["partition_table"],
            disk_size,
            partitions,
            c_used_bytes,
            e_used_bytes,
            min_source_free_after_bytes,
            config,
        )
    if config["corrupt_payload_marker"]:
        corrupt_payload_marker(output, partitions[1])
    if not config["malformed_manifest"]:
        mutate_manifest(output, config)
    if config["corrupt_primary_gpt_header"]:
        corrupt_primary_gpt_header(output)
    if config["corrupt_backup_gpt_header"]:
        corrupt_backup_gpt_header(output)
    if config["corrupt_gpt_entry_crc"]:
        corrupt_gpt_entry_crc(output)
    if config["truncate_image"]:
        truncate_image(output)
    print(f"Created disposable raw image: {output}")
    print("Note: raw fallback images are partitioned but not NTFS-formatted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
