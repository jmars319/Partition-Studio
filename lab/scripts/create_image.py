#!/usr/bin/env python3
"""Create a cross-platform disposable raw disk image with C and E partitions.

This is the portable fallback path. It writes partition tables only; it does not
format NTFS. On Windows, use create-test-image.ps1 for real NTFS-formatted VHDX
images.
"""

from __future__ import annotations

import argparse
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


def build_partitions(c_size: str, e_size: str) -> list[dict[str, Any]]:
    c_sectors = size_to_sectors(c_size)
    e_sectors = size_to_sectors(e_size)
    c_start = ALIGNMENT_SECTORS
    c_end = c_start + c_sectors - 1
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


def write_manifest(path: Path, scenario: str, partition_table: str, disk_size: int, partitions: list[dict[str, Any]]) -> None:
    manifest = {
        "schema": "partition-lab.image-manifest.v1",
        "scenario": scenario,
        "image": str(path),
        "format": "raw",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "disk": {
            "label": partition_table,
            "sector_size": SECTOR_SIZE,
            "alignment_sectors": ALIGNMENT_SECTORS,
            "size_bytes": disk_size,
            "partitions": [
                {
                    **partition,
                    "filesystem": "unformatted-placeholder",
                    "intended_filesystem": "ntfs",
                    "mountpoint": None,
                }
                for partition in partitions
            ],
        },
    }
    with path.with_suffix(path.suffix + ".manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a cross-platform raw tenra Partition Lab disk image.")
    parser.add_argument("--scenario", default="normal-c-e-layout", help="Scenario name used for default filename.")
    parser.add_argument("--output", help="Output image path. Must be under test-images by default.")
    parser.add_argument("--disk-size", default="12GiB", help="Disk image size. Default: 12GiB.")
    parser.add_argument("--c-size", default="4GiB", help="C partition size. Default: 4GiB.")
    parser.add_argument("--e-size", default="7GiB", help="E partition size. Default: 7GiB.")
    parser.add_argument("--partition-table", choices=("gpt", "mbr"), default="gpt", help="Partition table. Default: gpt.")
    parser.add_argument("--force", action="store_true", help="Replace an existing image.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing the image.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        disk_size = parse_size(args.disk_size)
        if disk_size % SECTOR_SIZE:
            raise ValueError("--disk-size must be sector-aligned")
        output = Path(args.output) if args.output else TEST_IMAGES_DIR / f"{args.scenario}.raw.img"
        output = output.resolve(strict=False)
        TEST_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if not path_is_under(TEST_IMAGES_DIR, output):
            raise ValueError(f"output must be under {TEST_IMAGES_DIR}")
        if output.exists() and not args.force:
            raise ValueError(f"output already exists; use --force: {output}")
        partitions = build_partitions(args.c_size, args.e_size)
        if partitions[-1]["end_sector"] >= disk_size // SECTOR_SIZE:
            raise ValueError("C and E partitions do not fit in the requested disk image")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    actions = [
        f"create sparse raw image: {output}",
        f"write {args.partition_table.upper()} partition table",
        "write manifest JSON",
    ]
    for action in actions:
        print(f"+ {action}")
    if args.dry_run:
        return 0

    if output.exists():
        output.unlink()
    create_sparse_file(output, disk_size)
    if args.partition_table == "gpt":
        write_gpt_image(output, disk_size, partitions)
    else:
        write_mbr_image(output, disk_size, partitions)
    write_manifest(output, args.scenario, args.partition_table, disk_size, partitions)
    print(f"Created disposable raw image: {output}")
    print("Note: raw fallback images are partitioned but not NTFS-formatted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
