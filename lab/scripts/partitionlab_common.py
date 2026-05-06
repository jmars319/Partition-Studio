#!/usr/bin/env python3
"""Shared model helpers for tenra Partition Lab scripts."""

from __future__ import annotations

import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any


SCHEMA_LAYOUT = "partition-lab.layout.v1"
SCHEMA_PLAN = "partition-lab.plan.v1"
SCHEMA_VERIFY = "partition-lab.verify.v1"

DEFAULT_ALIGNMENT_SECTORS = 2048
DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES = 1024**3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGES_DIR = PROJECT_ROOT / "test-images"

SYSTEM_BLOCK_DEVICE_DENYLIST = {
    "/dev/sda",
    "/dev/nvme0n1",
    "/dev/vda",
    "/dev/xvda",
    "/dev/disk0",
    r"\\.\physicaldrive0",
    r"\\?\physicaldrive0",
    "physicaldrive0",
    r"\\.\c:",
    r"\\?\c:",
    "c:",
}


class LayoutError(ValueError):
    """Raised when a mock or inspected layout is invalid."""


def load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=False))


def parse_size(value: str | int) -> int:
    """Parse binary sizes such as 40G, 40GiB, 1024M, or plain bytes."""
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("size must be positive")
        return value

    text = value.strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)", text)
    if not match:
        raise ValueError(f"invalid size: {value!r}")

    number = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {
        "": 1,
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "KI": 1024,
        "KIB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "MI": 1024**2,
        "MIB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "GI": 1024**3,
        "GIB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
        "TI": 1024**4,
        "TIB": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(f"unsupported size unit in {value!r}")
    result = int(number * multipliers[unit])
    if result <= 0:
        raise ValueError("size must be positive")
    return result


def human_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def disk(layout: dict[str, Any]) -> dict[str, Any]:
    try:
        return layout["disk"]
    except KeyError as exc:
        raise LayoutError("layout is missing disk") from exc


def partitions(layout: dict[str, Any]) -> list[dict[str, Any]]:
    parts = disk(layout).get("partitions")
    if not isinstance(parts, list):
        raise LayoutError("layout disk.partitions must be a list")
    return parts


def sector_size(layout: dict[str, Any]) -> int:
    value = disk(layout).get("sector_size", 512)
    if not isinstance(value, int) or value <= 0:
        raise LayoutError("disk.sector_size must be a positive integer")
    return value


def alignment_sectors(layout: dict[str, Any]) -> int:
    value = disk(layout).get("alignment_sectors", DEFAULT_ALIGNMENT_SECTORS)
    if not isinstance(value, int) or value <= 0:
        raise LayoutError("disk.alignment_sectors must be a positive integer")
    return value


def partition_size_sectors(partition: dict[str, Any]) -> int:
    return int(partition["end_sector"]) - int(partition["start_sector"]) + 1


def partition_size_bytes(partition: dict[str, Any], sector_bytes: int) -> int:
    return partition_size_sectors(partition) * sector_bytes


def normalized_partition(partition: dict[str, Any], sector_bytes: int) -> dict[str, Any]:
    result = dict(partition)
    result["size_sectors"] = partition_size_sectors(partition)
    result["size_bytes"] = partition_size_bytes(partition, sector_bytes)
    return result


def find_partition(layout: dict[str, Any], label: str) -> dict[str, Any]:
    wanted = label.upper()
    for partition in partitions(layout):
        labels = {
            str(partition.get("label", "")).upper(),
            str(partition.get("name", "")).upper(),
        }
        if wanted in labels:
            return partition
    raise LayoutError(f"partition {label!r} not found")


def sorted_partitions(layout: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(partitions(layout), key=lambda item: int(item["start_sector"]))


def are_adjacent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return int(left["end_sector"]) + 1 == int(right["start_sector"])


def is_aligned_sector(sector: int, alignment: int) -> bool:
    return sector % alignment == 0


def validate_layout(layout: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if layout.get("schema") != SCHEMA_LAYOUT:
        issues.append({"severity": "error", "message": f"expected schema {SCHEMA_LAYOUT}"})

    try:
        sector_bytes = sector_size(layout)
        alignment = alignment_sectors(layout)
        disk_size = disk(layout).get("size_bytes")
        if not isinstance(disk_size, int) or disk_size <= 0:
            issues.append({"severity": "error", "message": "disk.size_bytes must be a positive integer"})

        previous_end = -1
        for partition in sorted_partitions(layout):
            start = int(partition["start_sector"])
            end = int(partition["end_sector"])
            label = partition.get("label") or partition.get("name") or partition.get("number")
            if start < 0 or end < start:
                issues.append({"severity": "error", "message": f"partition {label} has invalid sector bounds"})
            if start <= previous_end:
                issues.append({"severity": "error", "message": f"partition {label} overlaps a previous partition"})
            if not is_aligned_sector(start, alignment):
                issues.append({"severity": "error", "message": f"partition {label} start sector is not aligned"})
            if disk_size and (end + 1) * sector_bytes > disk_size:
                issues.append({"severity": "error", "message": f"partition {label} extends beyond disk size"})
            previous_end = end
    except (KeyError, TypeError, ValueError, LayoutError) as exc:
        issues.append({"severity": "error", "message": str(exc)})

    return issues


def _operation(
    step: int,
    op_id: str,
    action: str,
    status: str,
    writes: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step": step,
        "id": op_id,
        "action": action,
        "status": status,
        "writes": writes,
        "details": details or {},
    }


def plan_operation(
    layout: dict[str, Any],
    increase_bytes: int,
    target_label: str = "C",
    source_label: str = "E",
    min_source_free_after_bytes: int = DEFAULT_MIN_SOURCE_FREE_AFTER_BYTES,
) -> dict[str, Any]:
    """Build a write-free operation queue for the C/E expansion workflow."""
    issues = validate_layout(layout)
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []

    try:
        sector_bytes = sector_size(layout)
        alignment = alignment_sectors(layout)
        target = find_partition(layout, target_label)
        source = find_partition(layout, source_label)
    except LayoutError as exc:
        target = {}
        source = {}
        sector_bytes = 512
        alignment = DEFAULT_ALIGNMENT_SECTORS
        blockers.append({"id": "layout-invalid", "message": str(exc)})

    for issue in issues:
        if issue["severity"] == "error":
            blockers.append({"id": "layout-invalid", "message": issue["message"]})

    disk_state = disk(layout).get("operation_state") if "disk" in layout else None
    if disk_state:
        blockers.append({"id": "operation-state", "message": f"disk operation_state is {disk_state}"})

    disk_label = disk(layout).get("label") if "disk" in layout else None
    if disk_label not in {"gpt", "mbr"}:
        blockers.append({"id": "partition-table", "message": f"unsupported partition table {disk_label!r}"})
    elif disk_label == "mbr":
        warnings.append("MBR is supported only as a mock planning scenario; future real mode should prefer GPT.")

    if target and source:
        if source.get("encrypted"):
            blockers.append({"id": "source-encrypted", "message": f"{source_label} is encrypted or marked as encrypted"})

        fs_state = source.get("filesystem_state")
        if fs_state and fs_state != "clean":
            blockers.append({"id": "source-filesystem-state", "message": f"{source_label} filesystem state is {fs_state}"})

        if str(target.get("filesystem", "")).lower() != "ntfs":
            blockers.append({"id": "target-filesystem", "message": f"{target_label} filesystem is not recognizable NTFS"})
        if str(source.get("filesystem", "")).lower() != "ntfs":
            blockers.append({"id": "source-filesystem", "message": f"{source_label} filesystem is not recognizable NTFS"})

        if int(target["end_sector"]) >= int(source["start_sector"]):
            blockers.append({"id": "partition-order", "message": f"{target_label} must be before {source_label}"})
        elif not are_adjacent(target, source):
            blockers.append({"id": "partition-adjacency", "message": f"{target_label} must be immediately before {source_label}"})

    if increase_bytes % sector_bytes != 0:
        blockers.append({"id": "size-sector-alignment", "message": "requested increase is not sector aligned"})
        increase_sectors = math.ceil(increase_bytes / sector_bytes)
    else:
        increase_sectors = increase_bytes // sector_bytes

    if increase_sectors % alignment != 0:
        blockers.append({"id": "size-partition-alignment", "message": "requested increase is not aligned to the disk alignment boundary"})

    free_check: dict[str, Any] = {
        "source_free_bytes": None,
        "requested_increase_bytes": increase_bytes,
        "minimum_source_free_after_bytes": min_source_free_after_bytes,
        "source_free_after_bytes": None,
    }
    if source:
        source_free = source.get("free_bytes")
        if not isinstance(source_free, int):
            blockers.append({"id": "source-free-unknown", "message": f"{source_label} free space is unknown"})
        else:
            free_after = source_free - increase_bytes
            free_check["source_free_bytes"] = source_free
            free_check["source_free_after_bytes"] = free_after
            if free_after < min_source_free_after_bytes:
                blockers.append(
                    {
                        "id": "source-free-insufficient",
                        "message": (
                            f"{source_label} needs {human_bytes(increase_bytes)} plus "
                            f"{human_bytes(min_source_free_after_bytes)} remaining free space"
                        ),
                    }
                )

    destructive_status = "ready" if not blockers else "blocked"
    validate_status = "pass" if not [issue for issue in issues if issue["severity"] == "error"] else "fail"
    free_status = "pass" if free_check["source_free_after_bytes"] is not None and free_check["source_free_after_bytes"] >= min_source_free_after_bytes else "fail"

    expected_result: dict[str, Any] | None = None
    if target and source:
        target_size = partition_size_bytes(target, sector_bytes)
        source_size = partition_size_bytes(source, sector_bytes)
        expected_result = {
            "target_partition": {
                "label": target_label,
                "start_sector": int(target["start_sector"]),
                "end_sector": int(target["end_sector"]) + increase_sectors,
                "size_bytes": target_size + increase_bytes,
            },
            "source_partition": {
                "label": source_label,
                "start_sector": int(source["start_sector"]) + increase_sectors,
                "end_sector": int(source["end_sector"]),
                "size_bytes": source_size - increase_bytes,
                "expected_free_bytes": free_check["source_free_after_bytes"],
            },
        }

    operations = [
        _operation(
            1,
            "validate-disk",
            "validate disk",
            validate_status,
            False,
            {"issues": issues, "disk_label": disk_label},
        ),
        _operation(
            2,
            "validate-source-free-space",
            f"validate {source_label} has enough free space",
            free_status,
            False,
            free_check,
        ),
        _operation(
            3,
            "shrink-source-filesystem",
            f"shrink {source_label} filesystem",
            destructive_status,
            True,
            {"new_size_bytes": expected_result["source_partition"]["size_bytes"] if expected_result else None},
        ),
        _operation(
            4,
            "shrink-source-partition",
            f"shrink {source_label} partition",
            destructive_status,
            True,
            {"new_size_bytes": expected_result["source_partition"]["size_bytes"] if expected_result else None},
        ),
        _operation(
            5,
            "move-source-right",
            f"move {source_label} right",
            destructive_status,
            True,
            {"move_by_bytes": increase_bytes, "move_by_sectors": increase_sectors},
        ),
        _operation(
            6,
            "expand-target-partition",
            f"expand {target_label} partition",
            destructive_status,
            True,
            {"increase_bytes": increase_bytes, "increase_sectors": increase_sectors},
        ),
        _operation(
            7,
            "expand-target-filesystem",
            f"expand {target_label} filesystem",
            destructive_status,
            True,
            {"increase_bytes": increase_bytes},
        ),
        _operation(
            8,
            "verify-result",
            "verify result",
            "ready" if not blockers else "blocked",
            False,
            {"expected_result": expected_result},
        ),
    ]

    return {
        "schema": SCHEMA_PLAN,
        "scenario": layout.get("scenario"),
        "mode": layout.get("mode", "unknown"),
        "plan_status": "ready" if not blockers else "blocked",
        "input": {
            "target_label": target_label,
            "source_label": source_label,
            "increase_bytes": increase_bytes,
            "increase_human": human_bytes(increase_bytes),
            "minimum_source_free_after_bytes": min_source_free_after_bytes,
        },
        "blockers": blockers,
        "warnings": warnings,
        "operations": operations,
        "expected_result": expected_result,
    }


def simulated_after_layout(
    layout: dict[str, Any],
    increase_bytes: int,
    target_label: str = "C",
    source_label: str = "E",
) -> dict[str, Any]:
    sector_bytes = sector_size(layout)
    if increase_bytes % sector_bytes != 0:
        raise LayoutError("requested increase is not sector aligned")
    increase_sectors = increase_bytes // sector_bytes

    find_partition(layout, target_label)
    find_partition(layout, source_label)
    result = json.loads(json.dumps(layout))
    result["scenario"] = f"{layout.get('scenario', 'layout')}-simulated-after"

    for partition in partitions(result):
        label = str(partition.get("label") or partition.get("name"))
        if label.upper() == target_label.upper():
            partition["end_sector"] = int(partition["end_sector"]) + increase_sectors
            partition["free_bytes"] = int(partition.get("free_bytes") or 0) + increase_bytes
        elif label.upper() == source_label.upper():
            partition["start_sector"] = int(partition["start_sector"]) + increase_sectors
            if isinstance(partition.get("free_bytes"), int):
                partition["free_bytes"] = int(partition["free_bytes"]) - increase_bytes

    return result


def path_is_under(parent: Path, candidate: Path) -> bool:
    parent_resolved = parent.resolve()
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def is_block_device(path: Path) -> bool:
    try:
        return stat.S_ISBLK(path.stat().st_mode)
    except FileNotFoundError:
        return False


def _normalized_device_text(path: str | os.PathLike[str]) -> str:
    text = str(path).strip().replace("/", "\\").lower()
    while "\\\\" in text and not text.startswith("\\\\.\\") and not text.startswith("\\\\?\\"):
        text = text.replace("\\\\", "\\")
    return text


def is_windows_physical_drive(path: str | os.PathLike[str]) -> bool:
    text = _normalized_device_text(path)
    return bool(re.fullmatch(r"(\\\\[.?]\\)?physicaldrive[0-9]+", text))


def safety_assessment(path: str | os.PathLike[str], allow_block_device: bool = False) -> dict[str, Any]:
    target = Path(path)
    resolved = target.resolve(strict=False)
    under_test_images = path_is_under(TEST_IMAGES_DIR, resolved)
    block_device = is_block_device(resolved)
    normalized_target = _normalized_device_text(path)
    normalized_resolved = _normalized_device_text(resolved)
    windows_physical_drive = is_windows_physical_drive(path)
    denylisted = (
        str(resolved) in SYSTEM_BLOCK_DEVICE_DENYLIST
        or normalized_target in SYSTEM_BLOCK_DEVICE_DENYLIST
        or normalized_resolved in SYSTEM_BLOCK_DEVICE_DENYLIST
    )
    device_like = block_device or windows_physical_drive
    accepted = under_test_images and not denylisted and (not device_like or allow_block_device)
    return {
        "path": str(target),
        "resolved_path": str(resolved),
        "under_test_images": under_test_images,
        "block_device": block_device,
        "windows_physical_drive": windows_physical_drive,
        "denylisted_system_device": denylisted,
        "allow_block_device": allow_block_device,
        "accepted": accepted,
    }
